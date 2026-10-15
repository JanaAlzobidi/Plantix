"""Generate data/attendance_history.csv: the training data for the attendance model.

The file stands in for the records of three past editions (2023, 2024, 2025).
Each row is one past event: what its owner expected, and how many actually came.
The numbers are synthetic but follow patterns organizers describe, for example:
entrepreneurship sessions aimed at students regularly overflow, press events
draw fewer than expected, and registration events land close to their count.

    python3 scripts/make_history.py        # rewrites data/attendance_history.csv

The seed is fixed, so the file is the same on every machine.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "attendance_history.csv"
SEED = 2026
EDITIONS = ("2023", "2024", "2025")

# Hidden "truth" the model should rediscover: percentage-point effects on
# (actual / expected - 1) for open (walk-in) events.
FIELD_EFFECT = {"تقنية": 8, "ريادة أعمال": 6, "ابتكار": 4, "تصميم": 2, "إعلام": -6, "مراسم": 4}
AUDIENCE_EFFECT = {"طلاب": 12, "مهنيون": -2, "رواد أعمال": 4, "مستثمرون": -8, "الجمهور العام": 6, "إعلاميون": -10}
COMBO_EFFECT = {("ريادة أعمال", "طلاب"): 37, ("تقنية", "طلاب"): 20,
                ("ابتكار", "الجمهور العام"): 10, ("تصميم", "مهنيون"): -5}
NOISE = 6  # standard deviation, percentage points

# name, field, audience, admission, duration, expected range
CATALOG = [
    ("حفل الافتتاح", "مراسم", "الجمهور العام", "open", 90, (380, 480)),
    ("الكلمة الرئيسية", "مراسم", "الجمهور العام", "open", 60, (300, 420)),
    ("حفل الختام", "مراسم", "الجمهور العام", "open", 90, (350, 470)),
    ("ندوة التحول الرقمي", "تقنية", "مهنيون", "open", 90, (80, 120)),
    ("جلسة الحوسبة السحابية", "تقنية", "مهنيون", "open", 60, (50, 90)),
    ("جلسة الأمن السيبراني", "تقنية", "طلاب", "open", 90, (60, 100)),
    ("جلسة مستقبل الذكاء الاصطناعي", "تقنية", "طلاب", "open", 60, (70, 110)),
    ("لقاء مطوري الألعاب", "تقنية", "طلاب", "open", 60, (40, 80)),
    ("عرض تقنيات المدن الذكية", "تقنية", "الجمهور العام", "open", 60, (80, 150)),
    ("جلسة التقنية للشركات الناشئة", "تقنية", "رواد أعمال", "open", 60, (40, 70)),
    ("ورشة تحليل البيانات", "تقنية", "طلاب", "registration", 120, (25, 40)),
    ("ورشة الذكاء الاصطناعي", "تقنية", "طلاب", "registration", 180, (25, 40)),
    ("ورشة البرمجة للمبتدئين", "تقنية", "طلاب", "registration", 240, (25, 40)),
    ("جلسة ريادة الأعمال", "ريادة أعمال", "طلاب", "open", 60, (60, 90)),
    ("جلسة من الفكرة إلى المشروع", "ريادة أعمال", "طلاب", "open", 60, (50, 80)),
    ("جلسة التوظيف", "ريادة أعمال", "طلاب", "open", 60, (50, 80)),
    ("قصص مؤسسين", "ريادة أعمال", "رواد أعمال", "open", 60, (50, 90)),
    ("عرض الشركات الناشئة", "ريادة أعمال", "مستثمرون", "open", 120, (80, 120)),
    ("حوار التمويل الجريء", "ريادة أعمال", "مستثمرون", "open", 60, (40, 70)),
    ("جلسة الامتياز التجاري", "ريادة أعمال", "مهنيون", "open", 60, (40, 70)),
    ("لقاء المستثمرين", "ريادة أعمال", "مستثمرون", "registration", 60, (30, 50)),
    ("معرض الابتكار", "ابتكار", "الجمهور العام", "open", 120, (150, 300)),
    ("عروض المخترعين", "ابتكار", "الجمهور العام", "open", 60, (60, 120)),
    ("حوار الطاولة المستديرة", "ابتكار", "مهنيون", "open", 90, (35, 60)),
    ("جلسة الابتكار في القطاع الحكومي", "ابتكار", "مهنيون", "open", 60, (50, 90)),
    ("هاكاثون مصغر", "ابتكار", "طلاب", "open", 120, (40, 70)),
    ("ورشة الطباعة ثلاثية الأبعاد", "ابتكار", "طلاب", "registration", 120, (15, 25)),
    ("ورشة تصميم تجربة المستخدم", "تصميم", "طلاب", "registration", 90, (20, 30)),
    ("جلسة الهوية البصرية", "تصميم", "طلاب", "open", 60, (40, 70)),
    ("مراجعة ملفات المصممين", "تصميم", "مهنيون", "open", 60, (30, 50)),
    ("جلسة التصميم والاستدامة", "تصميم", "الجمهور العام", "open", 60, (50, 90)),
    ("المؤتمر الصحفي", "إعلام", "إعلاميون", "open", 45, (150, 220)),
    ("لقاء صناع المحتوى", "إعلام", "الجمهور العام", "open", 60, (60, 110)),
    ("جلسة الإعلام الرقمي", "إعلام", "طلاب", "open", 60, (40, 70)),
    ("ورشة كتابة المحتوى", "إعلام", "طلاب", "registration", 60, (20, 30)),
]


def main():
    rng = random.Random(SEED)
    rows = []
    for edition in EDITIONS:
        for name, field, audience, admission, duration, (low, high) in CATALOG:
            # most catalog events run every edition; a few skip one
            if rng.random() < 0.08:
                continue
            for _ in range(2 if rng.random() < 0.5 else 1):  # some run twice
                expected = rng.randrange(low, high + 1, 5) if high - low >= 10 else rng.randint(low, high)
                if admission == "registration":
                    ratio = rng.uniform(0.86, 1.0)  # registered seats, minus no-shows
                else:
                    pts = FIELD_EFFECT[field] + AUDIENCE_EFFECT[audience] + COMBO_EFFECT.get((field, audience), 0)
                    ratio = 1 + (pts + rng.gauss(0, NOISE)) / 100
                rows.append({
                    "edition": edition, "program_name": name, "field": field, "audience": audience,
                    "admission": admission, "duration_min": duration,
                    "expected_attendance": expected, "actual_attendance": max(1, round(expected * ratio)),
                })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{OUT.name}: {len(rows)} events from {len(EDITIONS)} editions")


if __name__ == "__main__":
    main()
