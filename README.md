# Truth or Fables (website)

Modern static site for the **Truth or Fables** archive — subjects library, recommended books, testimonies, and contact.

**Live preview (Kyle’s deploy):** https://truth-or-fables.vercel.app  

This repo is **static HTML/CSS** (no build step). Perfect for Vercel, Netlify, or GitHub Pages.

---

## For Daniah — put this on *your* GitHub + Vercel

You do **not** need Kyle’s Vercel account. Use your own free GitHub + Vercel.

### Option A — Fork (easiest, ~2 minutes)

1. Open: https://github.com/Topperman67/truth-or-fables  
2. Click **Fork** (top right) → create under **your** GitHub username.  
3. Go to https://vercel.com/new and sign in with **your** GitHub.  
4. **Import** the forked repo `truth-or-fables`.  
5. Leave settings default (static site, no build command needed).  
6. Click **Deploy**.  
7. Copy your URL (e.g. `https://truth-or-fables-xxxx.vercel.app`).

Vercel will auto-redeploy whenever you push to `main` on **your** fork.

### Option B — “Use this template” (clean copy, no fork link)

1. Open: https://github.com/Topperman67/truth-or-fables/generate  
2. Name it anything (e.g. `truth-or-fables`) under **your** account.  
3. Import that new repo into **your** Vercel (same as steps 3–7 above).

### Option C — Upload zip (no git command line)

1. Download release zip:  
   https://github.com/Topperman67/truth-or-fables/archive/refs/heads/main.zip  
2. On GitHub → **New repository** → create empty public repo.  
3. On the empty repo page → **uploading an existing file** → drag the unzipped contents in → Commit.  
4. Import that repo into your Vercel.

### Vercel settings (if asked)

| Field | Value |
|--------|--------|
| Framework Preset | **Other** |
| Build Command | *(leave empty)* |
| Output Directory | `.` (root) |
| Install Command | *(leave empty)* |

`vercel.json` already enables clean URLs (`/books`, `/subjects`, `/library/01`, etc.).

---

## Local preview

```bash
# from repo root
python3 -m http.server 8080
# open http://localhost:8080
```

## Site map

| Path | Page |
|------|------|
| `/` | Home |
| `/subjects` | Subject library hub |
| `/library/01` … `/library/10` | Category lists |
| `/library/articles/...` | Article pages |
| `/books` | Recommended books (each card opens Amazon / magazine) |
| `/testimonies` | Reader testimonies |
| `/contact` | Contact table |

## Notes

- Content is drawn from the public Truth or Fables / Life Assurance Ministries archive.  
- Books are **recommendations only** — the site does not sell books.  
- No API keys or secrets are required to host this site.

## License / ownership

You may fork, re-deploy, and maintain your own copy. Keep original source attribution where articles link back to archive URLs.
