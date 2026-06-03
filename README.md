# 📋 Import Document Verification System

A production-ready Streamlit web application that **automatically verifies import/export documents** stored in Google Drive folders linked from a Google Sheet — eliminating the need for manual column-by-column checking.

---

## ✨ Features

| Feature | Detail |
|---|---|
| Google OAuth 2.0 | Secure login; only users with existing Sheet/Drive access can operate it |
| Smart Document Detection | Keyword-based matching handles naming variations (`INV`, `INVOICE`, `COMM INV` → all match **INV**) |
| Batch Sheet Updates | Writes `X` markers back to the sheet in efficient batch calls |
| Live Progress | Real-time scan progress bar and status log |
| Dashboard KPIs | Total brands, completed, incomplete, documents found/missing |
| Filtering & Search | Filter results by status, missing document type, or brand name |
| CSV & Excel Export | One-click export with a separate summary sheet |
| Render Deployment | `render.yaml` included for zero-config Render deploys |

---

## 🗂️ Project Structure

```
import_document_verifier/
├── app.py                  # Streamlit UI & entry point
├── auth.py                 # Google OAuth 2.0 flow
├── config.py               # All constants, column map, keyword map
├── drive_scanner.py        # Google Drive folder scanner
├── sheet_reader.py         # Reads rows + extracts hyperlinks
├── sheet_writer.py         # Batch-writes results back to the sheet
├── document_matcher.py     # Keyword-based document detection
├── dashboard.py            # Orchestration pipeline
├── logger.py               # Rotating log file + console handler
├── utils.py                # URL/string helpers
│
├── requirements.txt
├── render.yaml
├── .gitignore
│
├── .streamlit/
│   └── secrets.toml        # Local dev credentials (git-ignored)
└── logs/
    └── app.log             # Rotating application log
```

---

## ⚙️ Setup — Google Cloud Console

### 1. Create a Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com/).
2. Click **New Project** → give it a name (e.g. `import-doc-verifier`).

### 2. Enable APIs

In **APIs & Services → Library**, enable:

- **Google Sheets API**
- **Google Drive API**
- **Google OAuth2 API** (usually enabled by default)

### 3. Create OAuth 2.0 Credentials

1. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Application type: **Web application**.
3. Name: `Import Doc Verifier`.
4. Authorised redirect URIs — add **both**:
   - `http://localhost:8501` ← for local development
   - `https://YOUR-APP-NAME.onrender.com` ← for production (add after Render deploy)
5. Click **Create**.
6. Download the JSON or copy **Client ID** and **Client Secret**.

### 4. OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**.
2. User type: **Internal** (if all users are in your Google Workspace org) or **External**.
3. Fill in App name, support email, developer email.
4. Add scopes:
   - `../auth/spreadsheets`
   - `../auth/drive.readonly`
   - `openid`, `email`, `profile`
5. Add test users if using External type.

---

## 💻 Local Development

### Prerequisites

- Python 3.10+
- pip

### Install

```bash
git clone <your-repo>
cd import_document_verifier
pip install -r requirements.txt
```

### Configure secrets

Edit `.streamlit/secrets.toml`:

```toml
[google_oauth]
client_id     = "YOUR_CLIENT_ID.apps.googleusercontent.com"
client_secret = "YOUR_CLIENT_SECRET"
redirect_uri  = "http://localhost:8501"
```

### Run

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501).

---

## 🚀 Render Deployment

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_ORG/import-doc-verifier.git
git push -u origin main
```

> **Important:** Make sure `.streamlit/secrets.toml` is in `.gitignore`.

### 2. Create a Render Web Service

1. Go to [render.com](https://render.com/) → **New → Web Service**.
2. Connect your GitHub repo.
3. Render auto-detects `render.yaml`. Confirm settings.

### 3. Set Environment Variables in Render Dashboard

Under **Environment → Environment Variables**, add:

| Key | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | Your OAuth Client ID |
| `GOOGLE_CLIENT_SECRET` | Your OAuth Client Secret |
| `REDIRECT_URI` | `https://YOUR-APP-NAME.onrender.com` |

### 4. Add Render URL to Google OAuth

Go back to Google Cloud Console → **Credentials** → edit your OAuth client → add:

```
https://YOUR-APP-NAME.onrender.com
```

to the **Authorised redirect URIs**.

### 5. Deploy

Click **Manual Deploy → Deploy Latest Commit** (or push to trigger auto-deploy).

---

## 📊 Google Sheet Requirements

Your sheet must have these columns (exact names, any order — configure in `config.py` if different):

```
Ref No | LOC | Terms | Brand | Currency | Value | Invoice No | Mode | BOE No | BOE Date
PI | SWIFT | INV | PL | AWB | INS | BOE | FC | GP | OOC | EWAY | BOE ACK | COSTING | REMARKS
```

The **Brand** column must contain clickable Google Drive folder hyperlinks.

### Adjusting column layout

Edit `SHEET_COLUMNS` in `config.py` to match your actual column letters.

---

## 📝 Document Keyword Mapping

Customise detection keywords in `config.py`:

```python
DOCUMENT_TYPES = {
    "PI":      ["PI", "PROFORMA"],
    "SWIFT":   ["SWIFT"],
    "INV":     ["INV", "INVOICE", "COMM INV"],
    "PL":      ["PL", "PACKING LIST"],
    "AWB":     ["AWB"],
    "INS":     ["INS", "INSURANCE"],
    "BOE":     ["BOE"],
    "FC":      ["FC"],
    "GP":      ["GP"],
    "OOC":     ["OOC"],
    "EWAY":    ["EWB", "EWAY", "E-WAY"],
    "BOE ACK": ["BOE ACK", "ACKNOWLEDGEMENT", "ACK"],
    "COSTING": ["COSTING"],
}
```

Matching is **case-insensitive** and **space-insensitive**.

---

## 🔒 Security Notes

- Users must be authenticated via Google OAuth before any API calls are made.
- Only users who already have access to the sheet and Drive folders can retrieve data — no elevated permissions are granted.
- Credentials are stored only in Streamlit's ephemeral `session_state` (server memory) and are never persisted to disk.
- The `.streamlit/secrets.toml` file is git-ignored.

---

## 📋 Logs

Application logs are written to `logs/app.log` (rotating, max 10 MB × 5 backups).

```
2024-12-01 10:23:45 | INFO     | auth | Authenticated user: alice@company.com
2024-12-01 10:23:46 | INFO     | sheet_reader | Fetched 142 data rows
2024-12-01 10:23:47 | INFO     | drive_scanner | Scanned folder 'abc123' — found 5 file(s)
2024-12-01 10:23:47 | INFO     | sheet_writer | Batch update successful — wrote 13 cells
```

---

## 🐛 Troubleshooting

| Symptom | Fix |
|---|---|
| "OAuth not configured" error | Set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` env vars or `secrets.toml` |
| Redirect URI mismatch | Add your app's exact URL to Google OAuth client's Authorised Redirect URIs |
| "Permission denied" for a folder | The signed-in user doesn't have access to that Drive folder |
| Hyperlinks not extracted | Verify Brand cells use Insert → Link (or `=HYPERLINK(...)` formula) |
| Columns written to wrong cells | Adjust `SHEET_COLUMNS` in `config.py` to match your actual sheet layout |
