<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../figs/logo_dark.png">
    <img src="../../figs/lightmem_ego_crop.png" width="220" alt="LightMem-Ego">
  </picture>
</div>

# LightMem-Ego · Rokid AI Glasses App

<p>
  <a href="../../README.md">← Back to LightMem-Ego</a> &nbsp;·&nbsp;
  <a href="https://github.com/zjunlp/LightMem-Ego/releases/tag/v1.0.0">Download APK</a> &nbsp;·&nbsp;
  <a href="https://lightmem-ego.zjukg.cn/">Live Demo</a> &nbsp;·&nbsp;
  <a href="../backend/README.md">Backend</a>
</p>

The wearable client for [LightMem-Ego](../../README.md). The app captures first-person camera frames and microphone audio from Rokid AI Glass, uploads them to a LightMem-Ego backend over HTTP, and displays memory-grounded answers on the glasses screen. It demonstrates what an always-on personal AI assistant looks like at the edge.

Users can ask a preset question with a touchpad click or record a voice question with the physical button. When speaking isn't convenient, the same live session can be joined from the [web page](https://lightmem-ego.zjukg.cn/) and queried by typing instead.

The app uses standard Android APIs — Jetpack Compose UI, CameraX frame capture, `AudioRecord` microphone capture, and HTTP multipart upload — and needs no phone-side SDK at runtime.

## 🎬 Demonstration

<table>
  <tr>
    <td align="center" width="50%">
      <img src="assets/demo_slide7_cropped_for_emnlp_01.png" alt="Rokid AI Glass demo view showing a LightMem-Ego answer over the user's real-world scene" width="260" />
      <br><sub><b>User perspective</b><br>An answer over the real-world scene</sub>
    </td>
    <td align="center" width="50%">
      <img src="assets/glass_1_01.png" alt="LightMem-Ego glasses UI showing an audio question, answer page, latency, and touch controls" width="260" />
      <br><sub><b>Glasses app UI</b><br>Question, answer page, latency, and touch controls</sub>
    </td>
  </tr>
</table>

## 📱 Install The App

### Option 1 — Download the released APK

Grab `app-release.apk` from the [v1.0.0 release](https://github.com/zjunlp/LightMem-Ego/releases/download/v1.0.0/app-release.apk), then install it over ADB:

```bash
adb devices                       # confirm the glasses are visible
adb install -r app-release.apk
```

### Option 2 — Build from source

```bash
cd src/ai_glass_app
./gradlew assembleDebug           # Windows: .\gradlew.bat assembleDebug
```

The debug APK is written to `app/build/outputs/apk/debug/app-debug.apk`:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

> [!WARNING]
> Release builds need a signing keystore, which is **not** included in this repository — only debug builds work out of the box.

## 🚀 Requirements

- Rokid AI Glass, with ADB enabled.
- Android Studio, or the Android SDK command-line tools.
- A JDK compatible with the Android Gradle Plugin used by this project.
- A reachable LightMem-Ego backend API.

## 🕹️ Using The App

Launch it from the glasses launcher, or start it over ADB:

```bash
adb shell monkey -p cn.zjukg.lightmem.glass 1
```

The glasses have two control surfaces: a **touchpad** on the side of the temple arm, and a **physical button** near the front of the temple arm.

<img src="assets/glass_button.png" alt="The two control areas of the Rokid AI Glasses" width="400" />

After launching, you first see the welcome screen:

<img src="assets/welcome_page.png" alt="Welcome page of the app" width="260" />

Press and hold the touchpad to start a session. When the small text below the **“LightMem-Ego”** title shows a specific number of days, the app has connected to the backend; once the Answer section is ready, you can start asking questions:

<img src="assets/start_session.png" alt="After starting a session" width="260" />

There are two ways to ask:

- **Preset questions** — double click the touchpad to cycle through them, then click to ask the selected one.
- **Voice questions** — push the physical button to start recording, then push it again to stop and submit.

> [!TIP]
> Speaking isn't the only way in. Open the [web page](https://lightmem-ego.zjukg.cn/), select the **Rokid** mode (not *Rokid RTMP*, which is for testing other functions) and start — it joins the same live session running on the glasses, so you can type instead:

<img src="assets/frontend_rokid.png" alt="Asking questions about the live glasses session from the web page" />

## ⌨️ Controls Reference

| Input | Action |
| :--- | :--- |
| Touchpad, one-finger long press | Start or stop the real-time capture session. |
| Touchpad, one-finger click (running) | Ask the currently selected preset question. |
| Touchpad, one-finger double click | Select the next preset question. |
| Touchpad, two-finger long press | Show the next answer page when an answer has multiple pages. |
| Physical temple button (running) | Start recording a voice question; press again to stop and submit it. |

## 🔧 Configuration

Backend endpoint, input mode, preset questions, and capture rates live in one file:

[`app/src/main/java/cn/zjukg/lightmem/glass/lightmem_ego/LightMemEgoConfig.kt`](app/src/main/java/cn/zjukg/lightmem/glass/lightmem_ego/LightMemEgoConfig.kt)

| Setting | Default | Notes |
| :--- | :--- | :--- |
| `API_BASE_URL` | `https://lightmem-ego.zjukg.cn/api` | Change this to your own backend. |
| `INPUT_MODE` | `rokid_frame_audio` | Matches the backend's Rokid adapter path. |
| `PRESET_QUESTIONS` | Four everyday questions | Edit the list to suit your scenario. |
| `FRAME_INTERVAL_MS` | `1000` | Frame upload cadence. |
| `AUDIO_CHUNK_MS` | `1000` | Audio chunk length. |
| `ANSWER_TTS_ENABLED` | `false` | Set `true` to speak answers aloud. |

> [!IMPORTANT]
> `API_BASE_URL` points at our hosted demo server by default. Change it to your own backend before capturing anything you would not want to upload elsewhere.

The backend must be started with `input_mode=rokid_frame_audio`, and it never calls the Rokid SDK — it reuses the standard stream, current-memory, short-term-memory, and query paths. See [`../backend/README.md`](../backend/README.md) for the API contract and timestamp rule.

## 📁 Project Layout

```text
src/ai_glass_app/
  app/src/main/java/cn/zjukg/lightmem/glass/
    activities/main/            # Android entry activity
    activities/lightmem_ego/    # Glasses UI and session state
    camera/                     # CameraX binding helper
    input/                      # Rokid key and touchpad input dispatcher
    ui/design/                  # Glasses-oriented UI components
    ui/theme/                   # Compose theme
    lightmem_ego/               # API client, audio/image helpers
  app/src/main/AndroidManifest.xml
  gradle/libs.versions.toml
```

## 🔐 Permissions

The app declares only what the glasses-side realtime flow needs:

```xml
<uses-permission android:name="android.permission.CAMERA" />
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.RECORD_AUDIO" />
```

- `CAMERA` — captures frames from the glasses camera.
- `RECORD_AUDIO` — captures microphone audio and voice questions.
- `INTERNET` — sends data to the configured backend service.

No external-storage permission is required, and Android automatic backup is disabled with `android:allowBackup="false"`.
