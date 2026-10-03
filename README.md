<div dir="rtl">

# claude-handoff

**המנוי או חלון 5 השעות עומדים להיגמר? Claude עוצר בעצמו, אורז את כל ההקשר לתיקיית handoff,
ונותן לך פרומפט מוכן להדבקה בסשן חדש או במנוי אחר. שם ממשיכים בדיוק מאותה נקודה.**

פלאגין ל-Claude Code (אפליקציית הדסקטופ והטרמינל). מתקינים פעם אחת, ומשם זה עובד לבד.

> **1.0.6: macOS ולינוקס, ו-ZIP שעולה.** קובץ ה-ZIP ש-GitHub מוריד ("Download ZIP") עולה עכשיו כמו שהוא ב-"Upload a
> plugin", כי שורש הריפו הוא הפלאגין. ב-Mac: Python נמצא גם כשהאפליקציה נפתחה מה-Dock (Homebrew, python.org), בלי
> חלון "התקנת כלי מפתחים" בכל קריאה, ו-handoff לא נופל כש-macOS חוסם גישה ל-Desktop (עובר ל-`~/handoffs`).

> **1.0.5:** באפליקציית הדסקטופ, העצירה כבר לא תלויה בכך שהמודל מציית לבדיקת המכסה. ה-sentinel קורא בעצמו את
> תוצאת `get_usage`, ומודל שמתעלם מבדיקה או מהוראת עצירה נחסם זמנית (ראו [איך הוא יודע](#איך-הוא-יודע-שהמכסה-נגמרת)).
> עדכון: [סעיף עדכון](#עדכון).

> **התקנת גרסה 1.0.3 ומטה? לעדכן לגרסה האחרונה (1.0.6).** אין שום אינדיקציה שהפלאגין שולח מידע החוצה (הוא לא שולח כלום לשום
> מקום). הבעיה שתוקנה: בגרסאות 1.0.3 ומטה, קובץ ה-ZIP של handoff יכול היה לכלול קובץ רגיש מתוך `workspace/`.
> לא לשתף ZIP שנוצר בגרסה ישנה. עדכון: [סעיף עדכון](#עדכון). לבדוק handoff ישן: אמור ל-Claude "תריץ verify על
> תיקיית ה-handoff הזו".

## התקנה

בתוך Claude Code:

```
/plugin marketplace add ofeklevy11/claude-handoff
/plugin install handoff@claude-handoff
```

או בשורה אחת מהטרמינל:

```bash
claude plugin marketplace add ofeklevy11/claude-handoff && claude plugin install handoff@claude-handoff
```

<details><summary>סקריפט התקנה (Windows / macOS / Linux)</summary>

```powershell
irm https://raw.githubusercontent.com/ofeklevy11/claude-handoff/v1.0.6/install.ps1 | iex
```
```bash
curl -fsSL https://raw.githubusercontent.com/ofeklevy11/claude-handoff/v1.0.6/install.sh | sh
```
</details>

<details><summary>העלאה כקובץ ZIP ("Upload a plugin" ב-claude.ai או באפליקציית הדסקטופ)</summary>

כל אחד מהשניים עובד:
- ה-ZIP ש-GitHub נותן: **Code ← Download ZIP** (`claude-handoff-main.zip`), מעלים כמו שהוא.
- ZIP נקי של הפלאגין בלבד מדף ה-[Releases](https://github.com/ofeklevy11/claude-handoff/releases) (`handoff-1.0.6.zip`),
  או בונים אותו בעצמכם: `python tools/build_zip.py` ← `dist/handoff-1.0.6.zip`.
</details>

זהו. פותחים **סשן חדש**, ו-handoff פעיל. לא צריך לערוך הגדרות: הסקיל וה-hooks נטענים מהפלאגין.

**דרישות:** Python 3.8 ומעלה.
- **macOS:** כל Python 3.8+ עובד: של Apple (`xcode-select --install`), Homebrew (`brew install python`) או python.org. הוא
  נמצא גם כשהאפליקציה נפתחה מה-Dock ולא רואה את ה-PATH של הטרמינל. בלי כלי המפתחים, `/usr/bin/python3` לא מורץ
  בכלל, כדי שלא יקפוץ חלון התקנה.
- **Linux:** `python3` (ב-Debian/Ubuntu: `sudo apt install python3`).
- **Windows:** גם Git Bash, שכבר מגיע עם Claude Code.
- Python במקום לא רגיל? `HANDOFF_PYTHON=/path/to/python3`.

**נבדק על:** Windows 11 (אפליקציית הדסקטופ של Claude Code, כולל תרגיל חי מקצה לקצה). חבילת הבדיקות רצה ב-CI על
Windows, macOS ו-Linux, עם Python 3.8 ו-3.12, וגם ב-Docker על Linux. התקנה חיה ובדיקת harness נבדקו רק ב-Windows.
[דוח השחרור](RELEASE-REPORT.html).

## מה קורה

| מתי | מה Claude עושה |
|---|---|
| חלון 5 השעות ב-70% | אזהרה שקטה: לא פותח משימה ארוכה בלי נקודת שמירה |
| **חלון 5 השעות ב-80%**, או שבועי ב-93% | **עוצר את העבודה**, מסיים רק את הפעולה שבאמצע, ומכין handoff |
| ידנית ("תכין handoff", "המנוי נגמר", "hand off this session") | אותו דבר, מתי שתרצה |
| בסשן החדש ("המשך מ-handoff") | קורא, מאמת שהמצב תואם, ממשיך מהצעד הבא |

תיקיית ה-handoff נוצרת ב-`Desktop/handoffs`. אם אין Desktop, או שאי אפשר לכתוב אליו (למשל macOS חוסם לאפליקציה גישה
ל-Desktop), היא נוצרת ב-`~/handoffs` והפקודה אומרת את זה:

```
2026-09-28_1412_<שם>/
├── HANDOFF.md        ← מסמך המצב: 11 סעיפים (מה גמור עם הוכחה, איפה עצרנו, הצעדים הבאים,
│                        החלטות, העדפות, מלכודות, איך לאמת, מה פתוח)
├── PROMPT.txt        ← להדבקה בסשן חדש על אותו מחשב (גם במנוי אחר)
├── PROMPT-FULL.md    ← עצמאי: למחשב אחר או ל-claude.ai, יחד עם ה-zip
├── context/          ← כל מה שכתבת בסשן מילה במילה, ציר זמן, קבצים, פקודות, קישורים, git
├── memory/           ← קבצי הזיכרון של הפרויקט (CLAUDE.md וכו')
└── workspace/        ← עותק, רק אם הסשן עבד בתיקייה זמנית של האפליקציה (בלי סודות ובלי קישורים החוצה)
```

לפני מסירה עובר **שער מכני**: אין סעיפים ריקים, כל סעיף פעם אחת, יש צעדים ממוספרים (ונתיב שלא קיים מקבל אזהרה),
העותק של תיקייה זמנית שלם, ו**אין סודות בשום קובץ**, כולל `workspace/`. מפתחות וטוקנים במסמכים מצונזרים,
ו-handoff עם סוד לא עובר ולא נוצר לו ZIP.

## איך הוא יודע שהמכסה נגמרת

| איפה | מקור המספרים |
|---|---|
| **אפליקציית הדסקטופ** | הכלי המובנה `get_usage`, אותם מספרים שבכרטיס השימוש. בדיקה שקטה כל 15 דקות, ומ-60% ומעלה כל 5 דקות. ה-sentinel קורא את התוצאה בעצמו ומחליט אם לעצור, כך שהמודל רק צריך לקרוא לכלי. עובד מיד אחרי ההתקנה |
| **טרמינל** | Claude Code מעביר את `rate_limits` ל-statusline. בפעם הראשונה Claude שואל אם לחבר "גשר" שקורא אותם. ה-statusline שלך לא משתנה, ו-`statusline off` מחזיר את ההגדרות בדיוק ומסיר את הגשר. settings.json לא תקין? הגשר מסרב ולא נוגע בו |

**מודל שמתעלם (1.0.5):** בדיקה שהמודל התעלם ממנה במשך 2 קריאות לכלים, או הוראת עצירה שהתעלם ממנה פעם אחת, גורמות
ל-sentinel לדחות את הקריאה הבאה ל-Write, Edit, MultiEdit, NotebookEdit או Bash, עם הסיבה. הוא לא דוחה Read, Grep או
Glob, לא את הפקודות של handoff עצמו, ולא סוכני-משנה. לכל היותר 3 דחיות לכל בקשה, ואז הוא משחרר.

## לראות שזה עובד (תרגיל, בדקה)

אמור ל-Claude: **"תעשה תרגיל handoff"**. הוא מוריד זמנית את הסף ל-1% **לסשן הזה בלבד**, אתה נותן לו משימה
של כמה צעדים, ואחרי דקה של עבודה הוא נעצר ומכין handoff אמיתי. סשנים אחרים לא מושפעים, והתרגיל נכבה לבד.

## הגדרות

`~/.claude/handoff/config.json`:
```json
{ "five_hour": {"warn": 70, "act": 80}, "seven_day": {"warn": 85, "act": 93},
  "probe_minutes": 15, "out_dir": "D:/my-handoffs" }
```
משימות מתוזמנות וריצות `-p` לא מושפעות, כי אין שם מי שידביק את הפרומפט. להכללתן:
`HANDOFF_UNATTENDED=1`.

## פרטיות

הכל מקומי. הפלאגין לא שולח שום דבר לשום מקום, קורא רק את התמליל המקומי של הסשן, ומצנזר סודות
במסמכים שהוא כותב. התיקייה המקומית שומרת הכל. ה-ZIP (למחשב אחר או לחשבון אחר) לא כולל את `CLAUDE.local.md`
ואת הזיכרון האוטומטי, ותיקיית הבית מופיעה בו כ-`~`.

## אבטחה ומגבלות ידועות

- **מה לא יוצא מהמחשב ב-`workspace/`:** קישורים (symlink, junction) שמצביעים מחוץ לתיקייה, התיקיות
  `.ssh .aws .kube .docker .gnupg`, קבצים עם שם של סוד (`.env*`, `.npmrc`, `.netrc`, `.git-credentials`,
  `.pypirc`, מפתחות `id_*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.ppk`, `credentials*.json` ועוד), וכל קובץ
  טקסט שנמצא בתוכו סוד. כולם רשומים בראש ה-HANDOFF עם המקור.
- **הזיהוי מבוסס תבניות** (מפתחות Anthropic/OpenAI/GitHub/AWS/Google/Stripe/Slack/HuggingFace/GitLab/npm,
  מפתחות פרטיים, JWT, Bearer/Basic, URL עם סיסמה, `password=`/`*_TOKEN=` עם ערך). סוד בפורמט לא מוכר יכול
  לעבור, וכך גם סיסמה שמועברת כארגומנט לפונקציה (`jwt.sign(x, 'secret')`) או בדגל של פקודה (`-p`, `-u`). **קבצים
  בינאריים לא נסרקים** (sqlite, docx, תמונות); קבצי טקסט ב-UTF-16/UTF-32 כן. לפני ששולחים ZIP למישהו אחר, כדאי להציץ בו.
- **כל מה שנאסף הוא נתונים, לא הוראות:** הסשן שמקבל את ה-handoff מקבל הוראה מפורשת לא לבצע הוראות שמופיעות
  בשמות קבצים, ב-git, בלוגים או בתוכן קבצים.
- **דיווח על בעיית אבטחה:** [GitHub Issues](https://github.com/ofeklevy11/claude-handoff/issues).

## עדכון

```bash
claude plugin marketplace update claude-handoff
claude plugin update handoff@claude-handoff
```
ואז לפתוח סשן חדש. (בתוך Claude Code: `/plugin` ← Marketplaces ← update.)

## הסרה

1. חיברת את גשר ה-statusline בטרמינל? קודם אמור ל-Claude "כבה את גשר ה-statusline של handoff".
2. `/plugin uninstall handoff@claude-handoff`, ואז `claude plugin marketplace remove claude-handoff`.
3. כבר הסרת והגשר עדיין פעיל? `python "$HOME/.claude/handoff/statusline_tee.py" --off` (PowerShell ו-bash; ב-cmd:
   `python "%USERPROFILE%\.claude\handoff\statusline_tee.py" --off`; ב-Mac: `python3`) מחזיר את ה-statusline
   המקורי בדיוק ומוחק את הגשר.
4. אופציונלי: למחוק את `~/.claude/handoff` (מצב פנימי). תיקיות ה-handoff ב-`Desktop/handoffs` שלך, למחוק או לשמור.

## בדיקות

```bash
python tests/run_tests.py        # 356 בדיקות, בלי Claude ובלי עלות: מניפסטים, צנזור, כל החלטות ה-sentinel,
                                 # hook כתהליך אמיתי, גשר ה-statusline, pipeline מלא עם שער חיובי ושלילי, תרגיל,
                                 # ו-1.0.4: קישורים, סודות ב-workspace, ZIP נייד, git, הזרקת מבנה, סשן אחד בתרגיל
                                 # ו-1.0.5: קריאת get_usage ב-hook, דחייה של כלי אחרי בדיקה או עצירה שהמודל התעלם מהן
                                 # ו-1.0.6: ZIP שעולה (גם של GitHub), Python מחוץ ל-PATH ב-Mac, בלי חלון כלי המפתחים,
                                 # Desktop חסום -> ~/handoffs, תיקיות דרך symlink, נתיבי macOS/Linux בשער
python tests/install_test.py     # התקנה אמיתית של הפלאגין לתיקיית הגדרות זמנית (בלי לגעת בשלך)
python tests/harness_test.py     # תהליך Claude Code אמיתי: הפלאגין נטען, ה-hook רץ, וההודעה מוזרקת למודל. בלי עלות
python tests/harness_test.py --installed   # אותו דבר על הפלאגין שמותקן אצלך, עם ההגדרות שלך
python tests/e2e.py              # סשן Claude אמיתי שעובד על משימה בזמן שהמכסה עולה. עובר רק אם הוא
                                 # עוצר באמצע ומפיק handoff שעובר את השער. דורש התחברות ל-claude בטרמינל, עולה טוקנים
```

</div>

---

## English

**claude-handoff** is a Claude Code plugin. When your 5-hour window, weekly limit or subscription is about to
run out, Claude stops by itself, packs the session into a handoff folder (a state document with 11 sections,
every user message verbatim, files, git, project memory, secrets redacted) and gives you a ready prompt to
paste into a new session or another account. You pick up exactly where you left off.

```
/plugin marketplace add ofeklevy11/claude-handoff
/plugin install handoff@claude-handoff
```

- **Desktop app:** reads the built-in `get_usage` tool (a silent probe every 15 min, every 5 min above 60%).
  Warns at 70%, stops and hands off at 80% (weekly: 93%).
- **Terminal:** Claude Code exposes `rate_limits` only to the statusline. On first use Claude offers to add a
  pass-through bridge. Your statusline looks the same, and `statusline off` restores settings.json exactly and
  removes the bridge. An invalid settings.json is never touched.
- **If the model ignores it (1.0.5):** a probe ignored for 2 tool calls, or a stop ignored for 1, makes the sentinel
  turn away the next Write, Edit, MultiEdit, NotebookEdit or Bash call with the reason (never Read, Grep or Glob, never
  the handoff's own commands, never subagents). At most 3 times per request, then it lets go.
- **Gate:** a handoff is only delivered when `finalize` prints `GATE: PASS`. That requires no empty or duplicate
  sections, numbered next steps (a missing path only warns), a complete copy of a temporary work dir, and zero secrets in
  any text file, `workspace/` included. The ZIP leaves out `CLAUDE.local.md` and auto-memory, and shows your home
  dir as `~`. Collected data (file names, git, logs, file contents) is marked as data, never instructions.
- **Try it:** tell Claude "run a handoff drill". The threshold drops to 1% for this session only (default 30 min,
  max 120), so it stops after a minute of work and produces a real handoff. Other sessions are not affected.
- **Security note for 1.0.3 and earlier:** nothing was ever sent anywhere, but a handoff ZIP could include a
  sensitive file from `workspace/`. Don't share ZIPs made by old versions. Update:
  `claude plugin marketplace update claude-handoff && claude plugin update handoff@claude-handoff`, then open a
  new session. Uninstalling with the terminal bridge on? `python "$HOME/.claude/handoff/statusline_tee.py" --off`
  (PowerShell or bash; `python3` on macOS).
- **1.0.6, macOS + Linux:** GitHub's "Download ZIP" uploads as is in "Upload a plugin" (the repo root is the plugin;
  a plugin-only ZIP: `python tools/build_zip.py` or the release asset). On macOS Python is found even when the app
  was opened from the Dock (Homebrew, python.org, Apple's), the `/usr/bin/python3` stub is never run without the
  developer tools (no install popup), and a Desktop that macOS will not let the app write to falls back to `~/handoffs`.
- Requires Python 3.8+ (macOS: `xcode-select --install`, `brew install python` or python.org; Linux: `python3`;
  Windows: plus Git Bash, which Claude Code already uses). Unusual location: `HANDOFF_PYTHON=/path/to/python3`.
  Everything stays local.
- Tests: `python tests/run_tests.py` (offline, 356 checks), `tests/install_test.py` (real plugin install
  into a throwaway config), `tests/harness_test.py` (real Claude Code process: plugin loads, hook fires, stop
  message is injected; free), `tests/e2e.py` (real headless Claude session: must stop mid-task and pass the gate).

MIT © Ofek Levy
