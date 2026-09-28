<div dir="rtl">

# claude-handoff

**המנוי או חלון 5 השעות עומדים להיגמר? Claude עוצר בעצמו, אורז את כל ההקשר לתיקיית handoff,
ונותן לך פרומפט מוכן להדבקה בסשן חדש או במנוי אחר. שם ממשיכים בדיוק מאותה נקודה.**

פלאגין ל-Claude Code (אפליקציית הדסקטופ והטרמינל). מתקינים פעם אחת, ומשם זה עובד לבד.

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
irm https://raw.githubusercontent.com/ofeklevy11/claude-handoff/main/install.ps1 | iex
```
```bash
curl -fsSL https://raw.githubusercontent.com/ofeklevy11/claude-handoff/main/install.sh | sh
```
</details>

זהו. פותחים **סשן חדש**, ו-handoff פעיל. לא צריך לערוך הגדרות: הסקיל וה-hooks נטענים מהפלאגין.
דרישות: Python 3.8 ומעלה. ב-Windows צריך גם Git Bash, שכבר מגיע עם Claude Code.

## מה קורה

| מתי | מה Claude עושה |
|---|---|
| חלון 5 השעות ב-70% | אזהרה שקטה: לא פותח משימה ארוכה בלי נקודת שמירה |
| **חלון 5 השעות ב-80%**, או שבועי ב-93% | **עוצר את העבודה**, מסיים רק את הפעולה שבאמצע, ומכין handoff |
| ידנית ("תכין handoff", "המנוי נגמר", "hand off this session") | אותו דבר, מתי שתרצה |
| בסשן החדש ("המשך מ-handoff") | קורא, מאמת שהמצב תואם, ממשיך מהצעד הבא |

תיקיית ה-handoff נוצרת ב-`Desktop/handoffs` (אם אין Desktop, ב-`~/handoffs`):

```
2026-09-28_1412_<שם>/
├── HANDOFF.md        ← מסמך המצב: 11 סעיפים (מה גמור עם הוכחה, איפה עצרנו, הצעדים הבאים,
│                        החלטות, העדפות, מלכודות, איך לאמת, מה פתוח)
├── PROMPT.txt        ← להדבקה בסשן חדש על אותו מחשב (גם במנוי אחר)
├── PROMPT-FULL.md    ← עצמאי: למחשב אחר או ל-claude.ai, יחד עם ה-zip
├── context/          ← כל מה שכתבת בסשן מילה במילה, ציר זמן, קבצים, פקודות, קישורים, git
├── memory/           ← קבצי הזיכרון של הפרויקט (CLAUDE.md וכו')
└── workspace/        ← עותק מלא, רק אם הסשן עבד בתיקייה זמנית של האפליקציה
```

לפני מסירה עובר **שער מכני**: אין סעיפים ריקים, יש צעדים ממוספרים, כל הנתיבים קיימים, ו**אין
סודות**. מפתחות וטוקנים מצונזרים, ו-handoff עם סוד לא עובר.

## איך הוא יודע שהמכסה נגמרת

| איפה | מקור המספרים |
|---|---|
| **אפליקציית הדסקטופ** | הכלי המובנה `get_usage`, אותם מספרים שבכרטיס השימוש. בדיקה שקטה כל 15 דקות, ומ-60% ומעלה כל 5 דקות. עובד מיד אחרי ההתקנה |
| **טרמינל** | Claude Code מעביר את `rate_limits` ל-statusline. בפעם הראשונה Claude שואל אם לחבר "גשר" שקורא אותם. ה-statusline שלך לא משתנה, ו-`statusline off` מחזיר את המצב הקודם |

## לראות שזה עובד (תרגיל, בדקה)

אמור ל-Claude: **"תעשה תרגיל handoff"**. הוא מוריד זמנית את הסף ל-1%, אתה פותח סשן חדש ונותן לו
משימה של כמה צעדים, ואחרי דקה של עבודה הוא נעצר ומכין handoff אמיתי. התרגיל נכבה לבד.

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
במסמכים שהוא כותב. תיקיית העבודה הזמנית מועתקת כמו שהיא, בלי קבצי `.env` ומפתחות.

## הסרה

```
/plugin uninstall handoff@claude-handoff
```
אם חיברת את הגשר בטרמינל, קודם אמור ל-Claude "כבה את גשר ה-statusline של handoff".

## בדיקות

```bash
python tests/run_tests.py        # 99 בדיקות, בלי Claude ובלי עלות: מניפסטים, צנזור, כל החלטות ה-sentinel,
                                 # hook כתהליך אמיתי, גשר ה-statusline, pipeline מלא עם שער חיובי ושלילי, תרגיל
python tests/install_test.py     # התקנה אמיתית של הפלאגין לתיקיית הגדרות זמנית (בלי לגעת בשלך)
python tests/harness_test.py     # תהליך Claude Code אמיתי: הפלאגין נטען, ה-hook רץ, והודעת העצירה מוזרקת למודל. בלי עלות
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
  pass-through bridge. Your statusline looks the same, and `statusline off` restores it.
- **Gate:** a handoff is only delivered when `finalize` prints `GATE: PASS`. That requires no empty sections,
  numbered next steps, existing paths and zero secrets.
- **Try it:** tell Claude "run a handoff drill". The threshold drops to 1% for 30 minutes, so the next session
  stops after a minute of work and produces a real handoff. The drill switches itself off afterwards.
- Requires Python 3.8+ (and Git Bash on Windows, which Claude Code already uses). Everything stays local.
- Tests: `python tests/run_tests.py` (offline, 99 checks), `tests/install_test.py` (real plugin install
  into a throwaway config), `tests/harness_test.py` (real Claude Code process: plugin loads, hook fires, stop
  message is injected; free), `tests/e2e.py` (real headless Claude session: must stop mid-task and pass the gate).

MIT © Ofek Levy
