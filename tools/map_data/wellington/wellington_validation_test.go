package main

import (
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"

	"capnproto.org/go/capnp/v3"
)

const (
	tileMinLat = -42.0
	tileMinLon = 174.0
	tileStep   = 0.25
	tileCount  = 8
)

type tileStats struct {
	File         string  `json:"file"`
	Size         int64   `json:"size_bytes"`
	MinLat       float64 `json:"min_lat"`
	MinLon       float64 `json:"min_lon"`
	MaxLat       float64 `json:"max_lat"`
	MaxLon       float64 `json:"max_lon"`
	Ways         int     `json:"ways"`
	NamedWays    int     `json:"named_ways"`
	SpeedWays    int     `json:"speed_ways"`
	DirectedWays int     `json:"directed_speed_ways"`
	NodeCount    int     `json:"node_count"`
}

type replaySample struct {
	Latitude   float64 `json:"latitude"`
	Longitude  float64 `json:"longitude"`
	Bearing    float64 `json:"bearing_degrees"`
	RoadName   string  `json:"road_name"`
	SpeedMPS   float64 `json:"speed_mps"`
	SourceTile string  `json:"source_tile"`
}

type validationSummary struct {
	TileCount               int            `json:"tile_count"`
	NonEmptyTileCount       int            `json:"non_empty_tile_count"`
	UniqueWays              int            `json:"unique_ways"`
	UniqueNamedWays         int            `json:"unique_named_ways"`
	UniqueSpeedWays         int            `json:"unique_speed_ways"`
	NameCoveragePercent     float64        `json:"name_coverage_percent"`
	SpeedCoveragePercent    float64        `json:"speed_coverage_percent"`
	RuntimeReplayCount      int            `json:"runtime_replay_count"`
	VerticalSeamReplays     int            `json:"vertical_seam_replays"`
	HorizontalSeamReplays   int            `json:"horizontal_seam_replays"`
	DuplicateCoverageChecks int            `json:"duplicate_coverage_checks"`
	Samples                 []replaySample `json:"samples"`
}

type decodedTile struct {
	stats        tileStats
	offline      Offline
	fingerprints map[string]struct{}
}

type wayRecord struct {
	way         Way
	fingerprint string
	tileFile    string
}

func tileFilename(minLat, minLon float64) string {
	return fmt.Sprintf("%.6f_%.6f_%.6f_%.6f", minLat, minLon, minLat+tileStep, minLon+tileStep)
}

func wayFingerprint(w Way) (string, error) {
	h := sha256.New()
	name, err := w.Name()
	if err != nil {
		return "", err
	}
	ref, err := w.Ref()
	if err != nil {
		return "", err
	}
	fmt.Fprintf(h, "%q|%q|%.9f|%.9f|%.9f|%.9f|%.9f|%.9f|%.9f|%t|", name, ref,
		w.MinLat(), w.MinLon(), w.MaxLat(), w.MaxLon(), w.MaxSpeed(),
		w.MaxSpeedForward(), w.MaxSpeedBackward(), w.OneWay())
	nodes, err := w.Nodes()
	if err != nil {
		return "", err
	}
	for i := 0; i < nodes.Len(); i++ {
		n := nodes.At(i)
		fmt.Fprintf(h, "%.9f,%.9f;", n.Latitude(), n.Longitude())
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func hasSpeed(w Way) bool {
	return w.MaxSpeed() > 0 || w.MaxSpeedForward() > 0 || w.MaxSpeedBackward() > 0
}

func effectiveSpeed(w Way, forward bool) float64 {
	if forward && w.MaxSpeedForward() > 0 {
		return w.MaxSpeedForward()
	}
	if !forward && w.MaxSpeedBackward() > 0 {
		return w.MaxSpeedBackward()
	}
	return w.MaxSpeed()
}

func almostEqual(a, b float64) bool {
	return math.Abs(a-b) < 1e-9
}

func decodeTile(t *testing.T, path string, expectedMinLat, expectedMinLon float64) decodedTile {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	msg, err := capnp.UnmarshalPacked(data)
	if err != nil {
		t.Fatalf("decode %s: %v", path, err)
	}
	offline, err := ReadRootOffline(msg)
	if err != nil {
		t.Fatalf("read root %s: %v", path, err)
	}
	if !almostEqual(offline.MinLat(), expectedMinLat) || !almostEqual(offline.MinLon(), expectedMinLon) ||
		!almostEqual(offline.MaxLat(), expectedMinLat+tileStep) || !almostEqual(offline.MaxLon(), expectedMinLon+tileStep) {
		t.Fatalf("unexpected bounds in %s", path)
	}
	if !almostEqual(offline.Overlap(), OVERLAP_BOX_DEGREES) {
		t.Fatalf("unexpected overlap in %s: %f", path, offline.Overlap())
	}

	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	stats := tileStats{
		File: filepath.Base(path), Size: info.Size(), MinLat: offline.MinLat(), MinLon: offline.MinLon(),
		MaxLat: offline.MaxLat(), MaxLon: offline.MaxLon(),
	}
	fingerprints := make(map[string]struct{})
	ways, err := offline.Ways()
	if err != nil {
		t.Fatalf("ways in %s: %v", path, err)
	}
	stats.Ways = ways.Len()
	for i := 0; i < ways.Len(); i++ {
		w := ways.At(i)
		nodes, err := w.Nodes()
		if err != nil || nodes.Len() < 2 {
			t.Fatalf("invalid nodes in %s way %d", path, i)
		}
		stats.NodeCount += nodes.Len()
		name, _ := w.Name()
		ref, _ := w.Ref()
		if name != "" || ref != "" {
			stats.NamedWays++
		}
		if hasSpeed(w) {
			stats.SpeedWays++
		}
		if w.MaxSpeedForward() > 0 || w.MaxSpeedBackward() > 0 {
			stats.DirectedWays++
		}
		for _, speed := range []float64{w.MaxSpeed(), w.MaxSpeedForward(), w.MaxSpeedBackward()} {
			if speed < 0 || speed > 50 {
				t.Fatalf("implausible speed %.3f m/s in %s", speed, path)
			}
		}
		for j := 0; j < nodes.Len(); j++ {
			n := nodes.At(j)
			if n.Latitude() < -90 || n.Latitude() > 90 || n.Longitude() < -180 || n.Longitude() > 180 {
				t.Fatalf("invalid coordinate in %s", path)
			}
		}
		fingerprint, err := wayFingerprint(w)
		if err != nil {
			t.Fatal(err)
		}
		fingerprints[fingerprint] = struct{}{}
	}
	return decodedTile{stats: stats, offline: offline, fingerprints: fingerprints}
}

func expectedTileFiles() map[string][2]float64 {
	expected := make(map[string][2]float64, tileCount*tileCount)
	for latIndex := 0; latIndex < tileCount; latIndex++ {
		for lonIndex := 0; lonIndex < tileCount; lonIndex++ {
			minLat := tileMinLat + float64(latIndex)*tileStep
			minLon := tileMinLon + float64(lonIndex)*tileStep
			expected[tileFilename(minLat, minLon)] = [2]float64{minLat, minLon}
		}
	}
	return expected
}

func readAllTiles(t *testing.T, tileDir string) (map[string]decodedTile, map[string]wayRecord) {
	t.Helper()
	expected := expectedTileFiles()
	entries, err := os.ReadDir(tileDir)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != len(expected) {
		t.Fatalf("expected 64 entries, got %d", len(entries))
	}
	tiles := make(map[string]decodedTile, len(expected))
	uniqueWays := make(map[string]wayRecord)
	for _, entry := range entries {
		if !entry.Type().IsRegular() {
			t.Fatalf("unexpected non-file member: %s", entry.Name())
		}
		bounds, ok := expected[entry.Name()]
		if !ok {
			t.Fatalf("unexpected tile name: %s", entry.Name())
		}
		decoded := decodeTile(t, filepath.Join(tileDir, entry.Name()), bounds[0], bounds[1])
		tiles[entry.Name()] = decoded
		ways, _ := decoded.offline.Ways()
		for i := 0; i < ways.Len(); i++ {
			w := ways.At(i)
			fingerprint, _ := wayFingerprint(w)
			if _, exists := uniqueWays[fingerprint]; !exists {
				uniqueWays[fingerprint] = wayRecord{way: w, fingerprint: fingerprint, tileFile: entry.Name()}
			}
		}
	}
	return tiles, uniqueWays
}

func validateExpectedCoverage(t *testing.T, tiles map[string]decodedTile, uniqueWays map[string]wayRecord) int {
	t.Helper()
	checks := 0
	for fingerprint, record := range uniqueWays {
		w := record.way
		for latIndex := 0; latIndex < tileCount; latIndex++ {
			for lonIndex := 0; lonIndex < tileCount; lonIndex++ {
				minLat := tileMinLat + float64(latIndex)*tileStep
				minLon := tileMinLon + float64(lonIndex)*tileStep
				if !Overlapping(w.MinLat(), w.MinLon(), w.MaxLat(), w.MaxLon(),
					minLat-OVERLAP_BOX_DEGREES, minLon-OVERLAP_BOX_DEGREES,
					minLat+tileStep+OVERLAP_BOX_DEGREES, minLon+tileStep+OVERLAP_BOX_DEGREES) {
					continue
				}
				checks++
				file := tileFilename(minLat, minLon)
				if _, ok := tiles[file].fingerprints[fingerprint]; !ok {
					t.Fatalf("way from %s missing expected overlap copy in %s", record.tileFile, file)
				}
			}
		}
	}
	return checks
}

func midpointReplay(t *testing.T, record wayRecord) (replaySample, bool) {
	t.Helper()
	nodes, err := record.way.Nodes()
	if err != nil || nodes.Len() < 2 {
		return replaySample{}, false
	}
	i := (nodes.Len() - 1) / 2
	a := nodes.At(i)
	b := nodes.At(i + 1)
	lat := (a.Latitude() + b.Latitude()) / 2
	lon := (a.Longitude() + b.Longitude()) / 2
	if lat <= tileMinLat || lat >= tileMinLat+2 || lon <= tileMinLon || lon >= tileMinLon+2 {
		return replaySample{}, false
	}
	bearing := Bearing(a.Latitude(), a.Longitude(), b.Latitude(), b.Longitude()) * TO_DEGREES
	position := Position{Latitude: lat, Longitude: lon, Bearing: bearing}
	data, err := FindWaysAroundLocation(lat, lon)
	if err != nil || len(data) == 0 {
		return replaySample{}, false
	}
	offline := readOffline(data)
	current, err := GetCurrentWay(CurrentWay{}, nil, offline, position, position, 5)
	if err != nil || !current.Way.HasNodes() {
		return replaySample{}, false
	}
	name := RoadName(current.Way)
	speed := effectiveSpeed(current.Way, current.OnWay.IsForward)
	if name == "" && speed <= 0 {
		return replaySample{}, false
	}
	return replaySample{Latitude: lat, Longitude: lon, Bearing: bearing, RoadName: name, SpeedMPS: speed, SourceTile: record.tileFile}, true
}

func seamReplay(t *testing.T, uniqueWays map[string]wayRecord, seam float64, vertical bool) int {
	t.Helper()
	passed := 0
	for _, record := range uniqueWays {
		w := record.way
		name := RoadName(w)
		if name == "" && !hasSpeed(w) {
			continue
		}
		nodes, err := w.Nodes()
		if err != nil {
			continue
		}
		for i := 0; i < nodes.Len()-1; i++ {
			a := nodes.At(i)
			b := nodes.At(i + 1)
			first := a.Longitude()
			second := b.Longitude()
			if !vertical {
				first = a.Latitude()
				second = b.Latitude()
			}
			if (first-seam)*(second-seam) > 0 || almostEqual(first, second) {
				continue
			}
			tCross := (seam - first) / (second - first)
			if tCross <= 0 || tCross >= 1 {
				continue
			}
			deltaT := math.Min(0.2, 0.00005/math.Abs(second-first))
			if tCross-deltaT <= 0 || tCross+deltaT >= 1 {
				continue
			}
			for _, fraction := range []float64{tCross - deltaT, tCross + deltaT} {
				lat := a.Latitude() + fraction*(b.Latitude()-a.Latitude())
				lon := a.Longitude() + fraction*(b.Longitude()-a.Longitude())
				data, err := FindWaysAroundLocation(lat, lon)
				if err != nil || len(data) == 0 {
					t.Fatalf("seam %.6f missing tile at %.8f,%.8f", seam, lat, lon)
				}
				position := Position{
					Latitude: lat, Longitude: lon,
					Bearing: Bearing(a.Latitude(), a.Longitude(), b.Latitude(), b.Longitude()) * TO_DEGREES,
				}
				current, err := GetCurrentWay(CurrentWay{}, nil, readOffline(data), position, position, 5)
				if err != nil || !current.Way.HasNodes() {
					t.Fatalf("map matching dropout across seam %.6f at %.8f,%.8f", seam, lat, lon)
				}
			}
			passed++
			if passed >= 5 {
				return passed
			}
		}
	}
	return passed
}

func writeReports(t *testing.T, reportDir string, tiles map[string]decodedTile, summary validationSummary) {
	t.Helper()
	if err := os.MkdirAll(reportDir, 0o755); err != nil {
		t.Fatal(err)
	}
	jsonData, err := json.MarshalIndent(summary, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(reportDir, "validation-summary.json"), append(jsonData, '\n'), 0o644); err != nil {
		t.Fatal(err)
	}

	file, err := os.Create(filepath.Join(reportDir, "tile-report.csv"))
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	w := csv.NewWriter(file)
	defer w.Flush()
	_ = w.Write([]string{"file", "size_bytes", "min_lat", "min_lon", "max_lat", "max_lon", "ways", "named_ways", "speed_ways", "directed_speed_ways", "nodes"})
	files := make([]string, 0, len(tiles))
	for name := range tiles {
		files = append(files, name)
	}
	sort.Strings(files)
	for _, name := range files {
		s := tiles[name].stats
		_ = w.Write([]string{
			s.File, strconv.FormatInt(s.Size, 10), fmt.Sprintf("%.6f", s.MinLat), fmt.Sprintf("%.6f", s.MinLon),
			fmt.Sprintf("%.6f", s.MaxLat), fmt.Sprintf("%.6f", s.MaxLon), strconv.Itoa(s.Ways),
			strconv.Itoa(s.NamedWays), strconv.Itoa(s.SpeedWays), strconv.Itoa(s.DirectedWays), strconv.Itoa(s.NodeCount),
		})
	}
}

func TestWellingtonPilot(t *testing.T) {
	tileDir := filepath.Join("offline", "-42", "174")
	tiles, uniqueWays := readAllTiles(t, tileDir)
	if len(uniqueWays) < 5000 {
		t.Fatalf("implausibly low unique way count: %d", len(uniqueWays))
	}

	nonEmpty := 0
	for _, tile := range tiles {
		if tile.stats.Ways > 0 {
			nonEmpty++
		}
	}
	for _, required := range []string{
		"-41.500000_174.750000_-41.250000_175.000000",
		"-41.250000_174.750000_-41.000000_175.000000",
	} {
		if tiles[required].stats.Ways < 100 {
			t.Fatalf("known Wellington road tile is unexpectedly sparse: %s has %d ways", required, tiles[required].stats.Ways)
		}
	}

	named := 0
	speed := 0
	for _, record := range uniqueWays {
		name, _ := record.way.Name()
		ref, _ := record.way.Ref()
		if strings.TrimSpace(name) != "" || strings.TrimSpace(ref) != "" {
			named++
		}
		if hasSpeed(record.way) {
			speed++
		}
	}
	nameCoverage := float64(named) / float64(len(uniqueWays)) * 100
	speedCoverage := float64(speed) / float64(len(uniqueWays)) * 100
	if nameCoverage < 50 {
		t.Fatalf("implausibly low name coverage: %.2f%%", nameCoverage)
	}
	if speedCoverage < 40 {
		t.Fatalf("implausibly low speed coverage: %.2f%%", speedCoverage)
	}

	coverageChecks := validateExpectedCoverage(t, tiles, uniqueWays)

	records := make([]wayRecord, 0, len(uniqueWays))
	for _, record := range uniqueWays {
		records = append(records, record)
	}
	sort.Slice(records, func(i, j int) bool { return records[i].fingerprint < records[j].fingerprint })
	samples := make([]replaySample, 0, 50)
	seenTiles := make(map[string]struct{})
	for _, record := range records {
		if len(samples) >= 50 {
			break
		}
		if !hasSpeed(record.way) {
			continue
		}
		if _, used := seenTiles[record.tileFile]; used && len(seenTiles) < 8 {
			continue
		}
		if sample, ok := midpointReplay(t, record); ok && sample.SpeedMPS > 0 {
			samples = append(samples, sample)
			seenTiles[record.tileFile] = struct{}{}
		}
	}
	if len(samples) < 20 {
		t.Fatalf("only %d runtime replay samples succeeded", len(samples))
	}

	verticalReplays := seamReplay(t, uniqueWays, 174.75, true)
	horizontalReplays := seamReplay(t, uniqueWays, -41.25, false)
	if verticalReplays == 0 || horizontalReplays == 0 {
		t.Fatalf("required Wellington seam replay missing: vertical=%d horizontal=%d", verticalReplays, horizontalReplays)
	}

	summary := validationSummary{
		TileCount: len(tiles), NonEmptyTileCount: nonEmpty, UniqueWays: len(uniqueWays),
		UniqueNamedWays: named, UniqueSpeedWays: speed, NameCoveragePercent: nameCoverage,
		SpeedCoveragePercent: speedCoverage, RuntimeReplayCount: len(samples),
		VerticalSeamReplays: verticalReplays, HorizontalSeamReplays: horizontalReplays,
		DuplicateCoverageChecks: coverageChecks, Samples: samples,
	}
	reportDir := os.Getenv("WELLINGTON_REPORT_DIR")
	if reportDir == "" {
		reportDir = "."
	}
	writeReports(t, reportDir, tiles, summary)
	t.Logf("validated %d tiles, %d unique ways, %.2f%% named, %.2f%% with speed, %d runtime samples",
		len(tiles), len(uniqueWays), nameCoverage, speedCoverage, len(samples))
}
