# NIDA Portal: Next.js frontend for the Form Reader

This is the screen your staff use. It does no reading itself. The photos go to
the Python **Form Reader** (OpenCV and the bundled character models, no OCR
service), and the portal shows what came back so a person can check it and save it.

```
 Browser ──►  NIDA Portal (Next.js, port 3000) ──/pyapi/*──►  Form Reader (Python, port 8000)
```

## Pages

| Page | What it is for |
|---|---|
| **Dashboard** (`/`) | Totals, this week vs last week, how much was read correctly before review, enrolments per day, sex, age groups, top regions, marital status, employment, form editions, recent records |
| **New Enrolment** (`/enrolment/new`) | Upload the photo of page 1 (sections A, B, C) and page 2 (D, E, F, G, H); each is checked straight away (right page? empty form?) → the reader reads both pages → each field shows the handwriting picture with an editable box under it, grouped by **Page 1** (A, B, C) and **Page 2** (D–H) and by section. The form's rules are checked as you edit. Each section has a **Confirm section** tick. **Save enrolment** only works when every section is ticked and no rule is broken |
| **Enrolments** (`/enrolments`) | Search saved records, open one, download its JSON |
| **Reader Training** (`/training`) | Separate from enrolment. Upload many photos of page 1, check each one (`/training/check`), train the reader and install the new model. Its dashboard shows samples and accuracy per character, mix-ups, advice on what to do next, and the training history |
| **Settings** (`/settings`) | Connection to the Python API, model dates, known form editions |
| **Logout** | Placeholder. There is no sign-in yet |

### Photo checks

Each photo is checked as soon as it is added (about 2–3 seconds). The portal
never refuses a photo on its own: it tells you what it noticed and you decide.

| What it notices | What you can do |
|---|---|
| The photo is page 2 but is in the "Page 1" box (or the other way round) | **Swap the photos** / **Move to page 2**, or *keep it* |
| Nothing is written on the page (empty form) | Choose another photo, or **The form is correct, use it** |
| The photo is not a page of Form 1A | Choose another photo, or *use it anyway* |
| Page 2 belongs to a different form edition than page 1, or the same photo is in both boxes | Choose another photo, or *keep it* |
| Page 2: a signature or stamp is missing in 59, 60, 68, 70 or 71 (on the voter-registration printing of page 2: 60, 61, 69, 71, 72). Every missing part is listed on its own line, and each box is shown with its picture and what was found. The same warning is shown again above the page 2 sections when checking the form | Choose another photo, or **They are there, continue** |
| Page 2: everything is there, but a signature is on top of a stamp of the same colour | Only a note ("look at the picture"); nothing to answer |

**Read the form** only works when **both** photos (page 1 and page 2) are added
and every note has been answered: a complete form has both pages. The Python
API refuses an upload with a page missing as well.

### Moving around the form

The **Form** panel on the left is the navigation: **Page 1** with sections A, B, C
and **Page 2** with sections D to H. Click a page to show it, or click a section
to go straight to it, even on the other page. It shows the page and section you
are in, problems to correct (red **!**), how many fields still need checking,
and a ✓ for confirmed sections. A dark bar above the sections says which page is
shown, with a button to the other page. On
narrow screens it becomes a bar across the top. Each section has its own colour
and letter, and its heading stays at the top of the screen while you scroll
through it. **All fields in section B are correct** confirms the section and
takes you to the next one, and **Next to confirm** jumps to the first section
not yet confirmed.

Fields marked **Please check** are the ones the reader was unsure about. Fields
you change are marked **Edited**. Dates must be DD/MM/YYYY.

### Sections and district dropdown

On arrival only section **A** is open. Clicking anywhere on a section's bar (or
the section in the left panel) opens it and closes the one that was open; clicking
the bar of the open section closes it. The **Confirm section** tick on the bar
does not open or close it.

Region, district and ward fields are dropdowns with your official lists (loaded
by the Python reader from your lookup service, see `formreader/app/lookup_settings.json`).
They are linked **section by section**:

- choosing a **region** shows only that region's districts ("— Choose district in TANGA —"),
- choosing a **district** shows only its wards,
- changing the region empties a district and ward that are not in it,
- choosing a district while the region is empty fills in its region.

Each section works on its own (place of birth in C, current residence in D,
permanent address in E, office in H). The names matching the handwriting are
chosen for you; under each dropdown it says what was written ("Read as HBEYA")
and whether it is a sure match or the closest one to check.

### Reader training

Training is separate from enrolment. Enrolment saves the correct record
(official place names, corrected spellings), which is not always what is
written, so it is not used for training.

1. **Upload photos** of page 1 on the Reader Training page, as many as you like.
   They are read in the background; photos of page 2, other papers and empty
   forms are listed as problems with the reason.
2. **Check next form**: type **exactly what is written**, one character per box,
   even spelling mistakes (MOHAMED stays MOHAMED). Editing one letter or retyping
   the whole word both work. Under each field it says whether it will be used
   ("7 characters · 7 boxes with writing") or not ("8 typed, 7 boxes"). There are
   no rules or dropdowns on this screen. **Confirm & next** goes straight to the
   next form.
   **Several people can check at the same time.** Type your name in **Your name** on the
   Reader Training page. A form you open is yours until you confirm or skip it, or close the
   page: the others see "Being checked by Asha" in the list, cannot open it, and
   **Check next form** gives them the next free form. If a form was left open with nothing
   typed for 10 minutes, someone else can **Take over this form**.
3. Every 10th form is a **test form**: checked the same way but never trained on;
   it measures whether a new model is better.
4. **Start training** (about 20 minutes). When it finishes the page shows the
   model in use and the new model side by side on the test forms. **Install**
   (the old pair is kept as a backup) or download the two `.npz` files.

The dashboard tells you where to improve: samples per character (needs more /
moderate / enough, red mark when often misread), characters to work on, the
most common mix-ups (written → read as), fields not used and why, the training
history, and "What to do next".

### Photos

Clicking a photo (the small page 1 / page 2 pictures on the check-and-confirm page, or
**Open photo** while checking a training form) opens it at the width of the screen. Scroll
up and down to see the whole page, zoom with **+ / −** (or Ctrl + mouse wheel), drag to move
around, and press Esc to close (`components/PhotoViewer.tsx`).

### Countries, postcodes and tick boxes

- **Country** fields (18, 23, 25, 40) are dropdowns from your lookup; TANZANIA is
  chosen whenever the writing looks like it. Only Tanzania has regions: choosing
  another country in section C or E empties region, district and ward and shows
  "No region list for KENYA".
- **Postcode** (34, 42) is grey and cannot be typed: it is region postcode +
  district postcode + ward postcode (17 + 1 + 06 = 17106) and changes as soon as
  the region, district or ward changes (`fillPostcodes` in `lib/places.ts`).
- **Sex, marital status, employment, citizenship** keep their buttons; the names
  come from your lookup, so they follow it if it changes.

### Form rules (logic checks)

The values are checked against the form's rules while you edit (for example:
phone number has 10 digits, middle name equals the father's first name, the
parents are old enough). A broken rule is shown in red under every field it
concerns and marked **Correct this**; that section cannot be confirmed and
**Save enrolment** stays off until it is corrected (**Go to the problem** jumps
there). The rules and their limits are set in the **Python reader**, not here:
`formreader/app/validation_rules.json` (numbers) and `formreader/app/validation.py`
(the checks). See "Where the logic is" in the Form Reader README.

### Where the logic is (portal side)

| What | File |
|---|---|
| Both photos required before **Read the form**; page / empty-form notes and their buttons | `app/enrolment/new/page.tsx` (`issuesFor`, `missing`, `canRead`) |
| Photo card showing the check result | `components/enrolment/UploadCard.tsx` |
| Signature / stamp boxes of page 2 with their pictures (the check itself is in the reader, `formreader/app/endorsements.py`) | `components/enrolment/EndorsementList.tsx`; note added in `issuesFor` (`app/enrolment/new/page.tsx`) |
| Rules re-checked after each change (calls `POST /api/validate`), red marks, Save blocked while a rule is broken | `app/enrolment/new/page.tsx` (`ruleIssues`, `errorsBySection`, `errorCount`) |
| A broken rule shown on its field | `components/enrolment/FieldRow.tsx` |
| Page 1 / Page 2 navigation with sections | `components/enrolment/SectionNav.tsx` |
| One section open at a time (A open on arrival); `openId`, `goTo` | `app/enrolment/new/page.tsx` |
| The whole section bar opens/closes it | `components/enrolment/SectionCard.tsx` (`section-head` click) |
| Region / district / ward dropdown (list from the reader, name pre-selected, "Read as …") | `components/enrolment/FieldRow.tsx` (`choices`) |
| Linked dropdowns: which names to offer, emptying / filling the related fields | `lib/places.ts` (`choicesFor`, `setPlace`); used in `app/enrolment/new/page.tsx` (`onFieldChange`) |
| Section card, confirm tick, "correct first" | `components/enrolment/SectionCard.tsx` |
| Calls to the Python API | `lib/api.ts` |
| Photo viewer (scroll, zoom, drag) | `components/PhotoViewer.tsx` |
| One person per training form: who you are (tab id + name), keeping the form open, "Being checked by …", take over | `lib/staff.ts`, `components/StaffName.tsx`, `app/training/check/page.tsx` (`hold`, heartbeat, `takeOver`, `goNext`), `app/training/page.tsx` (`checkNext`, `inUseByOthers`) |

## 1. What to install

* **Node.js 20 LTS** (18.18 or newer works): <https://nodejs.org>. Check with `node -v`.
* The **Form Reader** (the Python app) from the other folder, already working.

No other software is needed. The charts and icons are built in, so the only
packages are `next`, `react` and `react-dom`.

## 2. Run it (development)

Open two terminals.

**Terminal 1, the reader**
```bash
cd formreader
python run.py            # http://127.0.0.1:8000
```

**Terminal 2, the portal**
```bash
cd nida-portal
npm install              # first time only, downloads about 150 MB into node_modules
npm run dev              # http://localhost:3000
```

Open <http://localhost:3000>. The light at the bottom of the sidebar says
**Reader online** when the portal can reach the Python app.

## 3. Settings

Copy `.env.example` to `.env.local` if you need to change anything:

```bash
# Where the Python Form Reader runs (used by the Next.js server, not the browser)
FORMREADER_API=http://127.0.0.1:8000
```

The browser always calls `/pyapi/...` on the portal itself, and Next.js
forwards it to `FORMREADER_API`. Nothing extra is needed for CORS, and the
Python app can stay on `127.0.0.1`. Reading a two-page form takes about 10–20 s
on a CPU-only machine. The forward timeout is 3 minutes (`next.config.mjs`).

Optional: set `NEXT_PUBLIC_API_URL=http://<host>:8000/api` to make the browser
call the Python app directly instead.

Restart `npm run dev` after changing `.env.local`.

## 4. Run it for daily use (production)

```bash
npm run build
npm start                # http://localhost:3000
```

To let other computers in the office use it, run `npm start -- -H 0.0.0.0` and
open `http://<this-computer's-IP>:3000` on them. The Python app can stay on
`127.0.0.1` because only the portal talks to it.

## 5. Where the data goes

The portal stores nothing. When you press **Save enrolment**, the Python app writes:

* `formreader/data/output/<id>.json`: the checked record (the JSON you wanted, plus who/when/which sections were confirmed)
* Enrolment no longer collects training data. `formreader/training_data/` is filled only by the Reader Training page.

Back up `formreader/data/output` regularly.

## 6. Project layout

```
nida-portal/
  app/
    layout.tsx              sidebar + page shell
    globals.css             all styling (glass sidebar, cards, charts, review form)
    page.tsx                Dashboard
    enrolment/new/page.tsx  upload → check & confirm → saved
    enrolments/page.tsx     saved records + detail drawer
    training/page.tsx       Reader Training dashboard: upload, figures, characters, advice, train, install
    training/check/page.tsx checking one training form (type exactly what is written)
    settings/page.tsx       API connection, models, editions
    logout/page.tsx         placeholder until sign-in is added
  components/
    Sidebar.tsx, Icons.tsx
    charts/charts.tsx       area, donut, bars, columns, ring (plain SVG)
    enrolment/UploadCard.tsx, SectionNav.tsx, SectionCard.tsx, FieldRow.tsx
  lib/api.ts                all calls to the Python API + types
  lib/places.ts             linked region → district → ward dropdowns
  lib/sections.ts           section colours and names
  next.config.mjs           /pyapi → Python forward
```

## 7. Adding sign-in later

Every API call goes through `lib/api.ts`, so a login token can be added there in
one place. `app/logout/page.tsx` is where the session would be cleared.

## Notes

* Tested: strict TypeScript check of every file (0 errors), and the full flow in
  a real browser: upload two photos, read, edit, Save stays locked until all
  8 sections are ticked, save, then the dashboard, records, training and settings pages.
  Tested with real 1.4 photos (page 1 + page 2): page 1 alone (Read stays off),
  swapped photos, an empty page 2, a non-form picture, the same photo twice; then
  reading both pages, a rule caught (middle name SALDI vs father SAIDI), fixing it,
  a bad phone number blocking the section, confirming all 8 sections and saving.
* `next build` was not run where this was made, because package downloads were
  blocked there. If `npm run build` reports anything, send the message.
