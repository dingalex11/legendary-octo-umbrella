import csv
import glob
import os
import sys

def compile_speed_stats(csv_files):
    player_stats = {}
    has_speed_data = False

    for file in csv_files:
        print(f"Processing {os.path.basename(file)}...")
        try:
            with open(file, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    event_type = row.get("Event_Type", "")
                    team_name = row.get("Team", "")
                    player_name = row.get("Player", "")

                    if not team_name or not player_name or event_type not in ["TOSSUP", "TOSSUP_REBOUND"]:
                        continue

                    full_name = f"{team_name} - {player_name}"

                    if full_name not in player_stats:
                        player_stats[full_name] = {
                            "team": team_name,
                            "total_buzzes": 0,
                            "interrupt_attempts": 0,
                            "interrupt_correct": 0,
                            "interrupt_negs": 0,
                            "total_buzz_time": 0.0,
                            "total_interrupt_time": 0.0,
                            "fastest_buzz": float('inf'),
                            "fastest_correct_buzz": float('inf')
                        }

                    p = player_stats[full_name]
                    p["total_buzzes"] += 1

                    try:
                        points = int(row.get("Points", 0))
                    except ValueError:
                        points = 0

                    try:
                        buzz_time = float(row.get("Buzz_Time", 0.0))
                        if buzz_time > 0: has_speed_data = True
                    except (ValueError, KeyError):
                        buzz_time = 0.0

                    is_correct = row.get("Correct", "False") == "True"
                    buzzpoint = row.get("Buzzpoint", "").strip()

                    # NSB Rule: It's an interrupt if they didn't wait for "Full Read" or if they took a -4 penalty
                    is_interrupt = (buzzpoint.lower() != "full read" and buzzpoint != "") or (points == -4)

                    # --- Speed Math ---
                    if buzz_time > 0:
                        p["total_buzz_time"] += buzz_time
                        if buzz_time < p["fastest_buzz"]:
                            p["fastest_buzz"] = buzz_time
                        if is_correct and buzz_time < p["fastest_correct_buzz"]:
                            p["fastest_correct_buzz"] = buzz_time

                    # --- Interrupt Math ---
                    if is_interrupt:
                        p["interrupt_attempts"] += 1
                        if buzz_time > 0:
                            p["total_interrupt_time"] += buzz_time

                        if is_correct:
                            p["interrupt_correct"] += 1
                        elif points == -4:
                            p["interrupt_negs"] += 1

        except Exception as e:
            print(f"Error processing {file}: {e}")

    # --- CSV EXPORT ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(script_dir, "agentic_speed_interrupt_stats.csv")

    headers = [
        "Player", "Team", "Total Buzzes", "Interrupt Rate %", 
        "Interrupt Accuracy %", "Interrupt Neg Rate %", 
        "Fastest Overall Buzz (s)", "Fastest Correct Buzz (s)", 
        "Avg Buzz Time (s)", "Avg Interrupt Time (s)"
    ]

    leaderboard_data = []

    with open(output_file, mode="w", newline="", encoding="utf-8") as f_out:
        writer = csv.writer(f_out)
        writer.writerow(headers)

        for p_name, p in sorted(player_stats.items()):
            tot = p["total_buzzes"]
            int_att = p["interrupt_attempts"]
            int_corr = p["interrupt_correct"]
            int_negs = p["interrupt_negs"]
            
            # Percentages
            int_rate = (int_att / tot * 100) if tot > 0 else 0
            int_acc = (int_corr / int_att * 100) if int_att > 0 else 0
            neg_rate = (int_negs / int_att * 100) if int_att > 0 else 0

            # Timing 
            fast_all = p["fastest_buzz"] if p["fastest_buzz"] != float('inf') else 0.0
            fast_corr = p["fastest_correct_buzz"] if p["fastest_correct_buzz"] != float('inf') else 0.0
            avg_time = (p["total_buzz_time"] / tot) if tot > 0 else 0.0
            avg_int_time = (p["total_interrupt_time"] / int_att) if int_att > 0 else 0.0

            row = [
                p_name, p["team"], tot, f"{int_rate:.1f}%", f"{int_acc:.1f}%", f"{neg_rate:.1f}%",
                f"{fast_all:.3f}", f"{fast_corr:.3f}", f"{avg_time:.3f}", f"{avg_int_time:.3f}"
            ]
            writer.writerow(row)

            leaderboard_data.append({
                "name": p_name,
                "int_rate": int_rate,
                "int_acc": int_acc,
                "fast_corr": fast_corr,
                "avg_int_time": avg_int_time
            })

    print(f"\n✅ Speed & Interrupt stats saved to '{os.path.basename(output_file)}'")

    if not has_speed_data:
        print("\n⚠️  NOTICE: All speed metrics evaluated to 0.000s.")
        print("Please ensure you updated main.py to log 'Buzz_Time' in your CSVs!")

    # --- TERMINAL LEADERBOARD ---
    print("\n" + "="*50)
    print("⚡ SPEED & INTERRUPT LEADERBOARDS ⚡")
    print("="*50)

    print("⏱️ FASTEST CORRECT BUZZES (Sub-millisecond)")
    # Filter out 0.0 if no speed data exists yet
    valid_speed = [x for x in leaderboard_data if x["fast_corr"] > 0]
    top_speed = sorted(valid_speed, key=lambda x: x["fast_corr"])[:3]
    for i, p in enumerate(top_speed, 1):
        print(f"  {i}. {p['name']} - {p['fast_corr']:.3f} seconds")

    print("\n⚔️ MOST AGGRESSIVE (Highest Interrupt Rate)")
    top_aggr = sorted(leaderboard_data, key=lambda x: x["int_rate"], reverse=True)[:3]
    for i, p in enumerate(top_aggr, 1):
        if p["int_rate"] > 0:
            print(f"  {i}. {p['name']} - {p['int_rate']:.1f}% of buzzes were interrupts")

    print("\n🎯 DEADLIEST INTERRUPTERS (Highest Accuracy on Interrupts)")
    top_deadly = [p for p in leaderboard_data if p["int_rate"] > 25.0] # Must interrupt occasionally to qualify
    top_deadly = sorted(top_deadly, key=lambda x: x["int_acc"], reverse=True)[:3]
    for i, p in enumerate(top_deadly, 1):
        if p["int_acc"] > 0:
            print(f"  {i}. {p['name']} - {p['int_acc']:.1f}% Accuracy (Avg {p['avg_int_time']:.3f}s)")

    print("="*50 + "\n")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    search_pattern = os.path.join(script_dir, "*.csv")
    files = sys.argv[1:] if len(sys.argv) > 1 else glob.glob(search_pattern)

    out_file = os.path.join(script_dir, "agentic_speed_interrupt_stats.csv")
    if out_file in files: files.remove(out_file)

    if not files:
        print(f"No match CSV files found in: {script_dir}")
    else:
        compile_speed_stats(files)