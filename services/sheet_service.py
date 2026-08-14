import asyncio
import gspread
from typing import Optional
from config import SheetConfig

class SheetService:
    def __init__(self, config: SheetConfig = SheetConfig()):
        self.config = config
        self.gc = gspread.service_account(filename=self.config.CREDENTIALS_PATH)
        self.sheet = self.gc.open(self.config.SPREADSHEET_NAME).sheet1

    async def update_tossup(self, question_num: int, category: str, team: str, points: int, score_a: int, score_b: int):
        """Writes Tossup results to the correct row without blocking the event loop."""
        target_row = self.config.HEADER_ROW_OFFSET + question_num
        
        updates = [
            {"range": f"C{target_row}", "values": [[category]]},
            {"range": f"H{target_row}", "values": [[score_a]]},
            {"range": f"I{target_row}", "values": [[score_b]]},
        ]

        if team == "Team A":
            updates.append({"range": f"F{target_row}", "values": [[points]]})
        elif team == "Team B":
            updates.append({"range": f"K{target_row}", "values": [[points]]})

        # Run the synchronous gspread call in a background thread
        await asyncio.to_thread(self._batch_update, updates)
        print(f"[SHEET SERVICE]: Tossup {question_num} logged successfully.")

    async def update_bonus(self, question_num: int, team: str, points: int, score_a: int, score_b: int):
        """Writes Bonus results to the correct row."""
        target_row = self.config.HEADER_ROW_OFFSET + question_num
        
        updates = [
            {"range": f"H{target_row}", "values": [[score_a]]},
            {"range": f"I{target_row}", "values": [[score_b]]},
        ]

        if team == "Team A":
            updates.append({"range": f"G{target_row}", "values": [[points]]})
        elif team == "Team B":
            updates.append({"range": f"J{target_row}", "values": [[points]]})

        await asyncio.to_thread(self._batch_update, updates)
        print(f"[SHEET SERVICE]: Bonus {question_num} logged successfully.")

    def _batch_update(self, updates: list):
        for update in updates:
            self.sheet.update(range_name=update["range"], values=update["values"])