# Installing Ruyso

Download the file for your computer from the **Assets** list below. Each one has a matching
`.sha256` checksum.

| Computer | File |
|---|---|
| Mac with Apple silicon (M1 or later) | `Ruyso-<version>-macOS-arm64.dmg` |
| Mac with an Intel processor | `Ruyso-<version>-macOS-x86_64.dmg` |
| Windows 10 or 11 (64-bit) | `Ruyso-<version>-Windows-x64-Setup.exe` |
| Linux (x86_64) | `Ruyso-<version>-Linux-x86_64.AppImage` |

To check which Mac you have, open the Apple menu and choose **About This Mac**. If you see "Chip",
you have Apple silicon; if you see "Processor … Intel", you have an Intel Mac.

These builds are **not code-signed yet**, so your system will warn you the first time you open the
app. The steps below get you past that warning.

## macOS

1. Open the `.dmg` and drag **Ruyso** onto **Applications**.
2. Double-click Ruyso in Applications. macOS says *"Ruyso is damaged and can't be opened"* or
   *"Apple could not verify…"*. This means the app is not notarized by Apple; the file is not
   damaged. Click **Done** or **Cancel**, not **Move to Bin**.
3. Allow the app in **one** of these two ways:
   - **Terminal (recommended):** paste this command and press Return:

     ```
     xattr -dr com.apple.quarantine /Applications/Ruyso.app
     ```

   - **System Settings:** open **Privacy & Security**, scroll down to the message about Ruyso,
     click **Open Anyway**, and confirm with your password.
4. Open Ruyso again. You only need to do this once.

On macOS 15 (Sequoia) and later, right-clicking the app and choosing **Open** no longer bypasses
this warning. Use one of the two options in step 3 instead.

## Windows

1. Run `Ruyso-<version>-Windows-x64-Setup.exe`.
2. If Windows shows *"Windows protected your PC"*, click **More info**, then **Run anyway**.
3. Follow the installer. It installs Ruyso for your user account only, so it does not ask for
   administrator rights. Ruyso then appears in the Start menu.

## Linux

```
chmod +x Ruyso-<version>-Linux-x86_64.AppImage
./Ruyso-<version>-Linux-x86_64.AppImage
```

If the window does not open and the error mentions `xcb`, install Qt's X11 cursor library, for
example `sudo apt install libxcb-cursor0` on Debian or Ubuntu.

## Already have Python?

Ruyso is also on PyPI. It needs Python 3.12 or newer, and you must include the `[ui]` extra to get
the desktop app:

```
pipx install "ruyso[ui]"
ruyso
```

## Check that it works

Run the self-test from a terminal. It checks the installation end to end and prints `OK` if
everything works:

- macOS: `/Applications/Ruyso.app/Contents/MacOS/ruyso --self-test`
- Windows: `"%LOCALAPPDATA%\Programs\Ruyso\ruyso.exe" --self-test`. The result is written to
  `ruyso.log` in the current folder.
- Linux: `./Ruyso-<version>-Linux-x86_64.AppImage --self-test`
- PyPI install: `ruyso --self-test`
