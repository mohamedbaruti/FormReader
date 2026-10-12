# NIDA Enrolment (Android)

Reads NIDA Form 1A from photos **on the phone**: no computer and no internet connection needed.
It is the same Form Reader as on the computer (OpenCV, the character models, the form editions,
the page 1 / page 2 checks, the signature and stamp check and the form's rules), without Reader
Training.

## Install on the phone

1. On the phone, open **github.com/mohamedbaruti/FormReader/releases**, open the newest release and
   tap **NIDA-Enrolment.apk** to download it.
2. Open the downloaded file. The first time, Android asks to allow installing apps from this
   source (Chrome or My Files): allow it, go back, tap **Install**.
3. If Google Play Protect says it does not know the developer: **More details -> Install anyway**.
   (Every app that does not come from the Play Store gets this message.)
4. Open **NIDA Enrolment**. The first start takes up to a minute while the reader prepares itself.

Updates install over the old version and keep the saved enrolments (same signing key).

## Using it

New Enrolment -> for page 1 and page 2: **Take photo** (camera) or **Choose from phone** (gallery).
Each photo is checked (right page? empty? signatures and stamps on page 2). **Read the form** ->
check each section -> **Save enrolment**. Saved enrolments are in **Enrolments**; **JSON** saves a
record into the phone's Downloads.

Saved enrolments are kept in an SQLite database in the app's storage (they stay when the app is
updated; they are removed if the app is uninstalled). Photos taken are also kept in
Pictures/NIDA Enrolment.

The official region / district / ward lists come from the lookup service in
`app/lookup_settings.json` when the phone can reach it (same network); otherwise the last copy is
used, or the names are typed in.

## What is where

| Folder | What |
|---|---|
| `android/` | the Android app (Java + Chaquopy, which runs Python inside the app) |
| `android/app/src/main/python/app/` | the Form Reader (the same code as on the computer) |
| `android/app/src/main/python/app/model/` | the character models: replace `char_cnn.npz` and `char_mlp.npz` with your trained ones (from the computer's `formreader/app/model/`) and push: a new app is built |
| `android/app/src/main/python/nidamobile/` | starts the reader inside the app; `ui/` = the screens |
| `portal/` | the screens' source (the NIDA Portal); `ui-src/build-ui.sh` rebuilds `nidamobile/ui/` |
| `android/keystore/` | the app's signing key (keep it: a different key cannot update the installed app) |
| `.github/workflows/build-apk.yml` | builds the app on GitHub after every push |
