# Lyle Pilot v0.1.0 — comma 3X installation checklist

This release targets the comma 3X (`tizi`) and is based on sunnypilot staging
2026.003.000. Its functional changes are limited to the user interface, but it
is custom driving software and must be evaluated cautiously.

## Installation and recovery URLs

- Lyle Pilot v0.1.0: `https://installer.comma.ai/pythagora5/lyle-pilot-v0.1.0`
- sunnypilot staging recovery: `https://staging.sunnypilot.ai`

The words "Experimental Mode" on the Lyle Pilot startup screen identify this
fork build. They do not indicate that sunnypilot's driving Experimental Mode
toggle is enabled.

## Before uninstalling the current software

- [ ] Park the vehicle somewhere safe and well ventilated. Do not perform the
      installation or first validation while driving.
- [ ] Arrange stable power for the comma 3X for the entire installation. Do not
      disconnect the harness or cycle vehicle power during download, install,
      build, or reboot.
- [ ] Connect the device to reliable Wi-Fi.
- [ ] Photograph or write down the current software version, branch, vehicle
      selection, and any non-default sunnypilot settings.
- [ ] Keep both installation URLs above available on another device.
- [ ] Allow enough time to reinstall sunnypilot staging if validation fails.

## Install Lyle Pilot

- [ ] On the comma 3X, open **Settings → Software** and uninstall the currently
      installed driving software.
- [ ] After the device returns to setup, select **Custom Software**.
- [ ] Enter the complete Lyle Pilot URL shown above.
- [ ] Confirm the warning and let the device download, install, build, and
      reboot without interruption.
- [ ] Do not proceed if the installer reports a download, build, signature,
      storage, or thermal error.

## Stationary validation

Keep the vehicle parked for all checks in this section.

- [ ] Confirm the startup screen reads **Lyle Pilot**, **Experimental Mode**,
      and **v0.1.0**, with no clipping or overlap.
- [ ] Confirm the home screen and Settings open, scroll, and respond normally.
- [ ] Confirm the device recognizes the vehicle and shows normal harness/Panda,
      camera, GPS, storage, network, and temperature state.
- [ ] Confirm there are no **Process Not Running**, calibration, camera,
      controls, or system-unresponsive errors.
- [ ] With the vehicle on and stationary, confirm the on-road HUD displays the
      MAX card, centered speed, status ring, road/status bar, and the subtle
      **Lyle Pilot v0.1.0** signature.
- [ ] Trigger only safe, non-driving UI prompts where available and confirm
      alert text remains prominent. The signature must disappear for an active
      driving alert.
- [ ] Leave the device running for at least ten minutes and confirm the UI
      remains responsive and temperatures remain normal.

## First-drive validation

Only continue after every stationary check passes.

- [ ] Choose daylight, dry weather, a familiar low-traffic route, and a place
      where stopping safely is easy.
- [ ] Drive manually first and confirm speed, speed limit, road name, lane/path,
      lead-vehicle indication, and driver-monitoring UI are readable.
- [ ] Confirm sunlight and reflections do not make the muted text or blue path
      difficult to see.
- [ ] When safe and legal, perform one brief supervised engagement and remain
      ready to take control immediately.
- [ ] Confirm engaged, override, disengaged, warning, and critical colors are
      unambiguous. Stop testing if any alert is obscured or delayed.
- [ ] End the test immediately for crashes, missing camera/model overlays,
      frozen UI, repeated warnings, abnormal thermal behavior, or unexpected
      driving behavior.

## Roll back to sunnypilot staging

- [ ] Park safely and connect to stable Wi-Fi and power.
- [ ] Open **Settings → Software** and uninstall Lyle Pilot.
- [ ] From device setup, install `https://staging.sunnypilot.ai`.
- [ ] Let installation and reboot complete without interruption.
- [ ] Restore the recorded vehicle and sunnypilot settings, then repeat the
      stationary checks before driving.

Do not troubleshoot, reinstall, or change branches while the vehicle is moving.
