"""
make_sample_excel.py
---------------------
Generates an Excel workbook with 240 realistic test rows for the dashboard.
Run:  python make_sample_excel.py
"""

import random
from datetime import datetime, timedelta

import pandas as pd

random.seed(42)

doors = [
    ("A AND A LIFESTYLE - SANJOULI", "OR"),
    ("CITY MALL - SHIMLA", "SOR"),
    ("HIGH STREET - CHANDIGARH", "EOR"),
    ("TRENDY WEAR - MANDI", "OR"),
    ("LUXE AVENUE - SOLAN", "OR"),
]
brands = [
    ("Levis", "Shashank"),
    ("Rareism", "Lalit"),
    ("Rare Rabbit", "Lalit"),
    ("Jack & Jones", "Shashank"),
    ("Pepe Jeans", "Lalit"),
]

base_date = datetime(2025, 4, 1)
rows = []
for door, door_type in doors:
    for brand, cluster in brands:
        target = random.choice([180000, 220000, 300000, 420000, 520000])
        master_os = round(random.uniform(120000, 660000), 2)
        master_sixty = round(master_os * random.uniform(0.35, 0.7), 2)
        master_collection = round(target * random.uniform(0.38, 0.92), 2)

        for offset in range(20):
            current_date = base_date + timedelta(days=offset * 10 + random.randint(0, 9))
            date_str = current_date.strftime("%d-%b-%Y")
            amount = round(random.uniform(1500, 52000), 2)
            status = "RECEIVED" if random.random() > 0.25 else "PENDING"
            reminder = "" if status == "RECEIVED" else "Follow-up due"
            reminder_date = "" if status == "RECEIVED" else (current_date + timedelta(days=7)).strftime("%d-%b-%Y")
            commitment_date = "" if random.random() < 0.35 else (current_date + timedelta(days=12)).strftime("%d-%b-%Y")
            commitment_amount = round(amount * random.uniform(0.6, 1.3), 2) if commitment_date else 0

            rows.append({
                "DOOR": door,
                "DOOR TYPE": door_type,
                "CLUSTER": cluster,
                "O/S": master_os,
                "60+": master_sixty,
                "TARGET": target,
                "COLLECTION": master_collection,
                "ACH": f"{round((master_collection / target) * 100, 1)}%",
                "DATE": date_str,
                "AMOUNT": amount,
                "STATUS": status,
                "BRAND": brand,
                "Reminder Remark": reminder,
                "Reminder Date": reminder_date,
                "Commitment Date": commitment_date,
                "Commitment Amount": commitment_amount,
            })

df = pd.DataFrame(rows)
output_path = "sample_data.xlsx"

# Try to remove the file with retries
import time, os
max_retries = 5
for attempt in range(max_retries):
    try:
        if os.path.exists(output_path):
            os.chmod(output_path, 0o777)
            os.remove(output_path)
            break
    except PermissionError:
        if attempt < max_retries - 1:
            time.sleep(0.5)
        else:
            # Last resort: write to backup filename
            output_path = "sample_data_backup.xlsx"
            print(f"Could not overwrite {output_path}, using {output_path} instead")

# Write using pandas
df.to_excel(output_path, index=False)
print(f"Wrote {output_path} with {len(df)} rows.")
