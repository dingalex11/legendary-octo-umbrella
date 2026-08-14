import os
import sys
import json
import asyncio
import argparse
import time
import csv
import io
import base64
import numpy as np
import cv2
from pathlib import Path
from dotenv import load_dotenv
import os
import uvicorn
load_dotenv()

from core.events import Event, EventType
from core.state_machine import StateEngine, GameState
from services.judge_service import JudgeService
from services.ui_service import HTMLGUIService
from services.camera_service import VisionService 

class ScienceBowlModerator:
    def __init__(self, use_audio=True, use_camera=False, initial_bank=None):
        self.inbound_queue = asyncio.Queue()
        self.outbound_queue = asyncio.Queue()
        
        self.use_audio = use_audio
        self.use_camera = use_camera
        
        if not self.use_audio:
            print("🔇 [AUDIO DISABLED]: Falling back to silent mock audio mode.")
            
        try:
            self.judge = JudgeService()
        except Exception as e:
            print(f"⚠️ [WARNING]: Judge Service failed to initialize: {e}")
            self.judge = None

        self.state = StateEngine() 
        
        if self.use_camera:
            self.vision = VisionService(self.inbound_queue, self.outbound_queue)
        else:
            self.vision = None
            print("📷 [CAMERA DISABLED]: Vision Engine is OFF. Defaulting to manual/keyboard buzzers.")

        self.ui = HTMLGUIService(self.inbound_queue, self.outbound_queue, self.vision)

        self.match_log = []
        self.question_bank = initial_bank if initial_bank else []
        self.current_q_idx = 0

        self.custom_teams = {}
        self.custom_roster = {}

    def generate_csv(self):
        output = io.StringIO()
        fieldnames = ["Q_Num", "Event_Type", "Team", "Player", "Correct", "Points", "Buzzpoint", "Buzz_Time", "Score_A", "Score_B"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(self.match_log)
        return output.getvalue()

    def log_event(self, event_type: str, team: str, player: str, is_correct: bool, points: int, buzzpoint: str = "", buzz_time: float = 0.0):
        entry = {
            "Q_Num": self.state.question_number,
            "Event_Type": event_type,
            "Team": team,
            "Player": player,
            "Correct": is_correct,
            "Points": points,
            "Buzzpoint": buzzpoint,
            "Buzz_Time": f"{buzz_time:.3f}",
            "Score_A": self.state.team_a_score,
            "Score_B": self.state.team_b_score
        }
        self.match_log.append(entry)
        # Broadcast the new log entry directly to the UI for live updating
        self.outbound_queue.put_nowait({"type": "NEW_LOG_ENTRY", "payload": entry})
        
    async def process_admin_event(self, event):
        evt_type = event.type.name if hasattr(event.type, 'name') else str(event.type)

        if evt_type == "SAVE_ROSTER":
            self.custom_teams = event.payload.get("teams", {})
            self.custom_roster = event.payload.get("players", {})
            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "✅ Match Roster Locked In!"}})

        elif evt_type == "LOAD_BANK":
            self.question_bank = event.payload.get("bank", [])
            self.current_q_idx = 0
            self.state.question_number = 1
            self.state.team_a_score = 0
            self.state.team_b_score = 0
            self.state.transition_to(GameState.IDLE)
            self.match_log = []
            
            await self.outbound_queue.put({"type": "UPDATE_SCORE", "payload": {"score_a": 0, "score_b": 0}})
            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": f"✅ Loaded {len(self.question_bank)} new questions."}})
            
            # FORCE THE UI TO RESET TO TOSSUP MODE
            await self.outbound_queue.put({"type": "UI_STATE", "payload": {"show": "TOSSUP"}})
            
            await self.inbound_queue.put(Event(type=EventType.STATE_CHANGED, payload={}))
            
        elif evt_type == "ADJUST_SCORE":
            team = event.payload.get("team")
            delta = event.payload.get("delta", 0)
            
            if team == "Team A":
                self.state.team_a_score += delta
            elif team == "Team B":
                self.state.team_b_score += delta
                
            # Log the manual override so it appears in analytics and the scoresheet
            self.log_event("MANUAL_OVERRIDE", team, "Moderator", delta > 0, delta, "Override", 0.0)
            
            await self.outbound_queue.put({"type": "UPDATE_SCORE", "payload": {"score_a": self.state.team_a_score, "score_b": self.state.team_b_score}})
            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": f"🔧 Manual Override: {team} ({delta:+d})"}})
        
        elif evt_type == "EXPORT_CSV":
            csv_data = self.generate_csv()
            await self.outbound_queue.put({"type": "DOWNLOAD_CSV", "payload": {"csv_data": csv_data}})
            
        elif evt_type == "UPDATE_STATUS":
            if isinstance(event, dict):
                await self.outbound_queue.put(event)
            else:
                await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": event.payload})
            
        elif evt_type == "SAVE_CALIBRATION" and self.use_camera:
            self.vision.update_rois(event.payload)
        elif evt_type == "RESET_CALIBRATION" and self.use_camera:
            self.vision.clear_rois()
            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "✅ Camera ROIs Cleared!"}})
        elif evt_type == "CALIBRATE_BASELINE" and self.use_camera:
            self.vision.request_baseline_calibration()
        
        elif evt_type == "EDIT_LOG_ENTRY":
            q_num = event.payload.get("q_num")
            team = event.payload.get("team")
            column = event.payload.get("column") # Will be "TOSSUP" or "BONUS"
            
            # Clean the string just in case an asterisk sneaks through
            new_val = str(event.payload.get("new_val", "")).replace("*", "").strip()
            
            # 1. Find and edit the specific log entry
            for entry in self.match_log:
                if str(entry.get("Q_Num")) == str(q_num) and entry.get("Team") == team:
                    
                    # --- TOSSUP EDIT LOGIC ---
                    if column == "TOSSUP" and "TOSSUP" in entry.get("Event_Type", ""):
                        tokens = new_val.split()
                        if len(tokens) >= 2:
                            player_str = tokens[0]       # E.g., "P1"
                            score_str = tokens[1].upper() # E.g., "+4", "-4", or "X"
                            
                            entry["Player"] = player_str
                            
                            if score_str == 'X':
                                entry["Points"] = 0
                            else:
                                try:
                                    entry["Points"] = int(score_str.replace('+', ''))
                                except ValueError:
                                    entry["Points"] = 0
                                    
                        entry["Edited"] = True
                        if "Correct" in entry:
                            entry["Correct"] = entry["Points"] > 0
                            
                    # --- BONUS EDIT LOGIC ---
                    elif column == "BONUS" and entry.get("Event_Type") == "BONUS":
                        tokens = new_val.split()
                        if len(tokens) >= 1:
                            score_str = tokens[0].upper() # E.g., "10", "0", or "X"
                            
                            if score_str == 'X':
                                entry["Points"] = 0
                            else:
                                try:
                                    entry["Points"] = int(score_str.replace('+', ''))
                                except ValueError:
                                    entry["Points"] = 0
                                    
                        entry["Edited"] = True
                        if "Correct" in entry:
                            entry["Correct"] = entry["Points"] > 0

            # 2. Recalculate ALL cumulative scores from question 1
            temp_score_a, temp_score_b = 0, 0
            for entry in self.match_log:
                if entry.get("Team") == "Team A":
                    temp_score_a += entry.get("Points", 0)
                elif entry.get("Team") == "Team B":
                    temp_score_b += entry.get("Points", 0)
                    
                entry["Score_A"] = temp_score_a
                entry["Score_B"] = temp_score_b
                
            self.state.team_a_score = temp_score_a
            self.state.team_b_score = temp_score_b
            
            # 3. Push total math to the scoreboard headers
            await self.outbound_queue.put({"type": "UPDATE_SCORE", "payload": {"score_a": temp_score_a, "score_b": temp_score_b}})
            
            # 4. Re-broadcast the entire log to visually update the UI table
            for entry in self.match_log:
                await self.outbound_queue.put({"type": "NEW_LOG_ENTRY", "payload": entry})
                
            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "✏️ Scoresheet edited & recalculated."}})

        elif evt_type == "PROCESS_FRAME" and self.use_camera:
            frame_data = event.payload.get("frame_data", "")
            if not frame_data: return 
            if frame_data.startswith("data:image/jpeg;base64,"):
                frame_data = frame_data.replace("data:image/jpeg;base64,", "")
            try:
                img_bytes = base64.b64decode(frame_data)
                np_arr = np.frombuffer(img_bytes, np.uint8)
                if np_arr.size == 0: return 
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if frame is None: return 
                current_time = asyncio.get_running_loop().time()
                await self.vision.process_frame(frame, current_time)
            except Exception as e:
                print(f"❌ [FRAME DECODE ERROR]: {e}")

    async def wait_for_moderator_action(self, expected_event_types: list):
        if isinstance(expected_event_types, str):
            expected_event_types = [expected_event_types]
            
        # NEW: Added LOAD_BANK, SAVE_ROSTER, and EDIT_LOG_ENTRY to prevent them from being ignored
        admin_events = ["EXPORT_CSV", "SAVE_CALIBRATION", "RESET_CALIBRATION", "CALIBRATE_BASELINE", "PROCESS_FRAME", "PING", "UPDATE_STATUS", "PAUSE_MATCH", "ADJUST_SCORE", "EDIT_LOG_ENTRY", "FORCE_ACCEPT", "LOAD_BANK", "SAVE_ROSTER"]
        
        while True:
            event = await self.inbound_queue.get()
            evt_type = event.type.name if hasattr(event.type, 'name') else str(event.type)
            print(f"📥 [DEBUG]: Queue received event -> {evt_type}")
            if evt_type in admin_events:
                if evt_type not in ["PING", "PAUSE_MATCH"]:
                    await self.process_admin_event(event)
                continue 
                
            if evt_type in expected_event_types:
                return event
            elif evt_type in ["FORCE_RESET_STATE", "CHALLENGE"]:
                return Event(type="FORCE_RESET_STATE")

    async def _speak_and_wait(self, text: str):
        if not self.use_audio or not text:
            return
            
        requeue_events = []
        while not self.inbound_queue.empty():
            try:
                evt = self.inbound_queue.get_nowait()
                evt_type = evt.type.name if hasattr(evt.type, 'name') else str(evt.type)
                if evt_type != "READING_DONE":
                    requeue_events.append(evt)
            except asyncio.QueueEmpty:
                break
                
        for evt in requeue_events:
            self.inbound_queue.put_nowait(evt)

        await self.outbound_queue.put({"type": "START_READING", "payload": {"text": text}})
        
        while True:
            reply = await self.inbound_queue.get()
            evt_type = reply.type.name if hasattr(reply.type, 'name') else str(reply.type)
            
            if evt_type == "READING_DONE":
                break
            elif evt_type in ["PROCESS_FRAME", "PING", "UPDATE_STATUS", "PAUSE_MATCH", "EXPORT_CSV", "RESET_CALIBRATION", "SAVE_CALIBRATION", "CALIBRATE_BASELINE", "ADJUST_SCORE"]:
                if evt_type not in ["PING", "PAUSE_MATCH"]:
                    await self.process_admin_event(reply)
            else:
                self.inbound_queue.put_nowait(reply)
                await asyncio.sleep(0.05)

    async def _handle_tossup_attempt(self, q_data, allowed_team=None, skip_read=False):
        tossup_text = str(q_data.get('tossup_text', '')).strip()
        tossup_answer = str(q_data.get('tossup_answer', '')).strip()
        category = str(q_data.get('category', 'GENERAL')).strip()
        
        # Format multiple choice options for TTS
        tossup_options = q_data.get('tossup_options', [])
        options_spoken = " ".join(tossup_options) if tossup_options else ""
        
        prefix = f"Reading for {allowed_team} only. " if allowed_team else ""
        text_to_read = prefix + f"Tossup,  " + tossup_text + "  " + options_spoken
        
        safe_display_text = text_to_read if text_to_read else "[WARNING: PYTHON MEMORY HAS NO TEXT FOR THIS QUESTION]"

        self.state.transition_to(GameState.READING_TOSSUP)

        await self.outbound_queue.put({"type": "UPDATE_QUESTION", "payload": {
            "text": safe_display_text,
            "answer": tossup_answer,
            "category": category,
            "options": q_data.get('tossup_options', []),
            "visual": q_data.get('tossup_visual', False)
        }})
        
        if not skip_read:
            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "🔊 Reading Tossup..."}})
            if self.use_audio and text_to_read:
                await self.outbound_queue.put({"type": "START_READING", "payload": {"text": text_to_read}})
            else:
                print("[DEBUG]: Audio skipped (disabled or text was empty). Jumping to Buzz phase.")
                self.inbound_queue.put_nowait(Event(type=EventType.TIMEOUT, payload={}))
        else:
            # Instantly bypass the reading loop and jump straight to the 5-second buzz countdown
            self.inbound_queue.put_nowait(Event(type=EventType.READING_DONE, payload={}))
        
        buzz_event = None
        is_interrupt = False
        buzz_time = 0.0
        buzzpoint_word = "Full Read"
        
        start_time = asyncio.get_running_loop().time()

        while True:
            event = await self.inbound_queue.get()
            evt_type = event.type.name if hasattr(event.type, 'name') else str(event.type)
            
            if evt_type in ["EXPORT_CSV", "SAVE_CALIBRATION", "RESET_CALIBRATION", "CALIBRATE_BASELINE", "PROCESS_FRAME", "PING", "UPDATE_STATUS", "PAUSE_MATCH", "ADJUST_SCORE"]:
                if evt_type not in ["PING", "PAUSE_MATCH"]:
                    await self.process_admin_event(event)
                continue 
                
            if evt_type == ["FORCE_RESET_STATE", "CHALLENGE"]:
                return None, False, False, evt_type, 0.0, ""
                
            elif evt_type == "READING_DONE":
                break 
                
            elif evt_type == "BUZZ":
                team = event.payload.get('team', 'Unknown')
                if allowed_team and team != allowed_team:
                    continue 
                if self.state.handle_buzz(team, 0, True):
                    buzz_event = event
                    is_interrupt = True
                    break

        if not buzz_event:
            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "⏳ 5 Seconds to Buzz..."}})
            start_time = asyncio.get_running_loop().time() 
            try:
                while True:
                    elapsed = asyncio.get_running_loop().time() - start_time
                    remaining = 5.0 - elapsed
                    if remaining <= 0:
                        raise asyncio.TimeoutError()

                    event = await asyncio.wait_for(self.inbound_queue.get(), timeout=remaining)
                    evt_type = event.type.name if hasattr(event.type, 'name') else str(event.type)
                    
                    if evt_type in ["PROCESS_FRAME", "PING", "UPDATE_STATUS", "PAUSE_MATCH", "EXPORT_CSV", "RESET_CALIBRATION", "SAVE_CALIBRATION", "CALIBRATE_BASELINE", "ADJUST_SCORE"]:
                        if evt_type not in ["PING", "PAUSE_MATCH"]:
                            await self.process_admin_event(event)
                        continue

                    if evt_type == "FORCE_RESET_STATE":
                        return None, False, False, True, 0.0, ""
                    elif evt_type == "BUZZ":
                        team = event.payload.get('team', 'Unknown')
                        if allowed_team and team != allowed_team:
                            continue
                        if self.state.handle_buzz(team, 0, False): 
                            buzz_event = event
                            buzz_time = asyncio.get_running_loop().time() - start_time 
                            break
            except asyncio.TimeoutError:
                return None, False, False, False, 0.0, ""

        raw_team = buzz_event.payload.get('team', 'Unknown Team')
        raw_player = buzz_event.payload.get('player', 'Captain')
        
        team = self.custom_teams.get(raw_team, raw_team)
        player = self.custom_roster.get(raw_player, raw_player)
        
        self.state.transition_to(GameState.LISTENING_TOSSUP_ANSWER) 
        await self.outbound_queue.put({"type": "BUZZ", "payload": {"team": team, "player": player}})
        
        if is_interrupt and self.use_audio:
            wait_start = asyncio.get_running_loop().time()
            try:
                while asyncio.get_running_loop().time() - wait_start < 1.5:
                    time_left = 1.5 - (asyncio.get_running_loop().time() - wait_start)
                    if time_left <= 0: break
                    
                    reply = await asyncio.wait_for(self.inbound_queue.get(), timeout=time_left)
                    evt_type = reply.type.name if hasattr(reply.type, 'name') else str(reply.type)
                    
                    if evt_type == "LOG_BUZZPOINT":
                        buzzpoint_word = reply.payload.get("buzzpoint", "")
                        break
                    elif evt_type in ["PROCESS_FRAME", "PING", "UPDATE_STATUS", "PAUSE_MATCH", "EXPORT_CSV", "RESET_CALIBRATION", "SAVE_CALIBRATION", "CALIBRATE_BASELINE", "ADJUST_SCORE"]:
                        if evt_type not in ["PING", "PAUSE_MATCH"]:
                            await self.process_admin_event(reply)
                    else:
                        self.inbound_queue.put_nowait(reply)
                        await asyncio.sleep(0.05)
            except asyncio.TimeoutError:
                pass

        player_str = f"{player}" if player else ""
        phrase = f"{player_str}"
        await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": f"🔊 {phrase}"}})
        
        if self.use_audio:
            requeue_events = []
            while not self.inbound_queue.empty():
                try:
                    evt = self.inbound_queue.get_nowait()
                    evt_type = evt.type.name if hasattr(evt.type, 'name') else str(evt.type)
                    if evt_type != "READING_DONE":
                        requeue_events.append(evt)
                except asyncio.QueueEmpty:
                    break
            
            for evt in requeue_events:
                self.inbound_queue.put_nowait(evt)

            await self.outbound_queue.put({"type": "START_READING", "payload": {"text": phrase}})
            
            while True:
                reply = await self.inbound_queue.get()
                evt_type = reply.type.name if hasattr(reply.type, 'name') else str(reply.type)
                
                if evt_type == "READING_DONE":
                    break
                elif evt_type in ["PROCESS_FRAME", "PING", "UPDATE_STATUS", "PAUSE_MATCH", "EXPORT_CSV","RESET_CALIBRATION", "SAVE_CALIBRATION", "CALIBRATE_BASELINE", "ADJUST_SCORE"]:
                    if evt_type not in ["PING", "PAUSE_MATCH"]:
                        await self.process_admin_event(reply)
                else:
                    self.inbound_queue.put_nowait(reply)
                    await asyncio.sleep(0.05)
        
        spoken_answer = ""
        if self.use_audio:
            current_sys_time = time.time()
            await self.outbound_queue.put({
                "type": "START_LISTENING", 
                "payload": {"timeout": 8.0, "expires_at": current_sys_time + 8.0}
            })
            try:
                while True:
                    reply = await asyncio.wait_for(self.inbound_queue.get(), timeout=12.0)
                    evt_type = reply.type.name if hasattr(reply.type, 'name') else str(reply.type)
                    
                    if evt_type == "ANSWER_AUDIO":
                        await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "⏳ Transcribing Tossup..."}})
                        b64_audio = reply.payload.get("audio_data", "")
                        
                        if self.judge:
                            spoken_answer = await self.judge.transcribe_audio(b64_audio)
                        else:
                            spoken_answer = ""
                            
                        await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": f"🗣️ Heard: '{spoken_answer}'"}})
                        break
                        
                    elif evt_type in ["EXPORT_CSV", "SAVE_CALIBRATION", "RESET_CALIBRATION", "CALIBRATE_BASELINE", "PROCESS_FRAME", "PING", "UPDATE_STATUS", "PAUSE_MATCH", "ADJUST_SCORE"]:
                        if evt_type not in ["PING", "PAUSE_MATCH"]:
                            await self.process_admin_event(reply)
            except asyncio.TimeoutError:
                spoken_answer = ""
        else:
            await asyncio.sleep(1)
            spoken_answer = "Mitochondria"
            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": f"🎤 Capturing Mock Mic: '{spoken_answer}'"}})
        
        self.state.transition_to(GameState.EVALUATING_TOSSUP) 
        
        if self.judge:
            correct = await self.judge.evaluate_answer(
                spoken_answer, 
                tossup_answer, 
                category,
                is_multiple_choice=q_data.get('type', '') == 'MC'
            )
        else:
            correct = False
            
        return buzz_event.payload, correct, is_interrupt, False, buzz_time, buzzpoint_word

    async def run_game_loop(self):
        await asyncio.sleep(1)

        try:
            while True:
                if not self.question_bank or self.current_q_idx >= len(self.question_bank):
                    # NEW: Process the queue so LOAD_BANK and SAVE_ROSTER don't get stuck forever
                    while not self.inbound_queue.empty():
                        evt = self.inbound_queue.get_nowait()
                        await self.process_admin_event(evt)
                    
                    await asyncio.sleep(1)
                    continue
                q_data = self.question_bank[self.current_q_idx]
                
                await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": f"✅ Ready for Q{self.current_q_idx+1}. Click 'Start Tossup'"}})
                
                safe_preload_text = str(q_data.get('tossup_text', '')).strip()
                await self.outbound_queue.put({"type": "UPDATE_QUESTION", "payload": {
                    "text": safe_preload_text if safe_preload_text else "[WARNING: PYTHON MEMORY HAS NO TEXT FOR THIS QUESTION]", 
                    "answer": str(q_data.get('tossup_answer', '')),
                    "category": str(q_data.get('category', 'GENERAL')),
                    "options": q_data.get('tossup_options', []),
                    "visual": q_data.get('tossup_visual', False)
                }})
                
                # TELL UI TO ONLY SHOW TOSSUP BUTTON
                await self.outbound_queue.put({"type": "UI_STATE", "payload": {"show": "TOSSUP"}})
                
                action = await self.wait_for_moderator_action(["MANUAL_START_TOSSUP"])
                

                action_type = action.type.name if hasattr(action.type, 'name') else str(action.type)
                if action_type == "FORCE_RESET_STATE": continue 
                elif action_type == "CHALLENGE":
                    self.log_event("CHALLENGE", "None", "Moderator", False, 0, "Question Dead", 0.0)
                    self.state.next_question()
                    self.current_q_idx += 1
                    continue

                # HIDE BUTTONS WHILE READING/EVALUATING
                await self.outbound_queue.put({"type": "UI_STATE", "payload": {"show": "NONE"}})

                payload, correct, is_interrupt, interrupt_action, buzz_time, buzz_text = await self._handle_tossup_attempt(q_data)
                
                if interrupt_action == "FORCE_RESET_STATE": 
                    continue
                elif interrupt_action == "CHALLENGE":
                    self.log_event("CHALLENGE", "None", "Moderator", False, 0, "Question Dead", 0.0)
                    await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "⚠️ CHALLENGE! Clock paused. Edit scoresheet, then Start Next Tossup."}})
                    self.state.next_question()
                    self.current_q_idx += 1
                    continue
                
                bonus_earned_by = None
                tossup_ans_text = str(q_data.get('tossup_answer', ''))

                if payload and correct:
                    bonus_earned_by = payload['team']
                    self.state.apply_tossup_points(True) 
                    self.log_event("TOSSUP", payload['team'], payload['player'], True, 4, buzz_text, buzz_time)
                    await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": f"✅ Correct! 4 points to {bonus_earned_by}."}})
                    
                    await self._speak_and_wait("That is correct.")

                elif payload and not correct:
                    team = payload['team']
                    self.state.apply_tossup_points(False) 
                    other_team = "Team B" if team == "Team A" else "Team A"
                    skip_rebound = False
                    
                    if is_interrupt:
                        # Interrupt Penalty: -4 points and a pause for Moderator Override / Re-read
                        self.log_event("TOSSUP", team, payload['player'], False, -4, buzz_text, buzz_time)
                        await self.outbound_queue.put({"type": "UPDATE_SCORE", "payload": {"score_a": self.state.team_a_score, "score_b": self.state.team_b_score}})
                        await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": f"❌ NEG! Penalty applied. Waiting for Re-read..."}})
                        
                        await self._speak_and_wait("That is incorrect.")
                        await asyncio.sleep(1)
                        
                        # --- PAUSE FOR RE-READ OR OVERRIDE ---
                        await self.outbound_queue.put({"type": "UI_STATE", "payload": {"show": "REREAD", "overrides": True}})
                        action = await self.wait_for_moderator_action(["MANUAL_REREAD_TOSSUP", "FORCE_JUDGMENT"])
                        action_type = action.type.name if hasattr(action.type, 'name') else str(action.type)
                        
                        if action_type == "FORCE_JUDGMENT" and action.payload.get("correct"):
                            # REWIND STATE: Refund the -4, award +4, change to correct, and jump to bonus
                            self.state.apply_tossup_points(True)
                            if team == "Team A": self.state.team_a_score += 4
                            else: self.state.team_b_score += 4
                            
                            self.match_log[-1].update({"Correct": True, "Points": 4, "Score_A": self.state.team_a_score, "Score_B": self.state.team_b_score, "Edited": True})
                            await self.outbound_queue.put({"type": "NEW_LOG_ENTRY", "payload": self.match_log[-1]})
                            
                            bonus_earned_by = team
                            skip_rebound = True
                            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "🔧 Override: Marked Correct! Jumping to Bonus."}})
                        elif action_type == "CHALLENGE":
                            self.log_event("CHALLENGE", "None", "Moderator", False, 0, "Question Dead", 0.0)
                            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "⚠️ CHALLENGE! Clock paused. Edit scoresheet, then Start Next Tossup."}})
                            self.state.next_question()
                            self.current_q_idx += 1
                            continue
                        
                        if not skip_rebound:
                            await self.outbound_queue.put({"type": "UI_STATE", "payload": {"show": "NONE"}})
                            payload2, correct2, is_int2, interrupt_action2, buzz_time2, buzz_text2 = await self._handle_tossup_attempt(q_data, allowed_team=other_team)
                        
                    else:
                        # Full Read (No Penalty): 0 points, opposing team immediately gets 5 seconds
                        self.log_event("TOSSUP", team, payload['player'], False, 0, buzz_text, buzz_time)
                        await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": f"❌ Incorrect. 5 seconds for {other_team}."}})
                        
                        await self._speak_and_wait("That is incorrect.")
                        
                        payload2, correct2, is_int2, interrupt_action2, buzz_time2, buzz_text2 = await self._handle_tossup_attempt(q_data, allowed_team=other_team, skip_read=True)

                    # --- EVALUATE THE REBOUND ATTEMPT ---
                    if not skip_rebound:
                        if interrupt_action2 == "FORCE_RESET_STATE": 
                            continue
                        elif interrupt_action2 == "CHALLENGE":
                            self.log_event("CHALLENGE", "None", "Moderator", False, 0, "Question Dead", 0.0)
                            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "⚠️ CHALLENGE! Clock paused. Edit scoresheet, then Start Next Tossup."}})
                            self.state.next_question()
                            self.current_q_idx += 1
                            continue
                            
                        if payload2 and correct2:
                            bonus_earned_by = other_team
                            self.state.apply_tossup_points(True) 
                            self.log_event("TOSSUP_REBOUND", other_team, payload2['player'], True, 4, buzz_text2, buzz_time2)
                            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": f"✅ Correct! 4 points to {other_team}."}})
                            await self._speak_and_wait("That is correct.")
                            
                        elif payload2 and not correct2:
                            self.state.apply_tossup_points(False) 
                            if is_int2:
                                self.log_event("TOSSUP_REBOUND", other_team, payload2['player'], False, -4, buzz_text2, buzz_time2)
                                await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "❌ DOUBLE NEG! Penalty applied."}})
                            else:
                                self.log_event("TOSSUP_REBOUND", other_team, payload2['player'], False, 0, buzz_text2, buzz_time2)
                                await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "❌ Incorrect. No penalty."}})
                            await self._speak_and_wait(f"That is incorrect. The correct answer is {tossup_ans_text}.")
                            
                        else:
                            self.log_event("DEAD_TOSSUP", "None", "None", False, 0, "Time", 0.0)
                            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "⏰ Time expired on rebound."}})
                            await self._speak_and_wait(f"Time. The correct answer is {tossup_ans_text}.")

                else:
                    self.log_event("DEAD_TOSSUP", "None", "None", False, 0, "Time", 0.0)
                    await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "⏰ Time expired. No buzz."}})
                    await self._speak_and_wait(f"Time. The correct answer is {tossup_ans_text}.")

                await self.outbound_queue.put({"type": "UPDATE_SCORE", "payload": {"score_a": self.state.team_a_score, "score_b": self.state.team_b_score}})

                if bonus_earned_by:
                    self.state.transition_to(GameState.READING_BONUS) 
                    await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": f"🌟 BONUS for {bonus_earned_by}. Click 'Start Bonus'"}})
                    
                    safe_bonus_preload = str(q_data.get('bonus_text', '')).strip()
                    await self.outbound_queue.put({"type": "UPDATE_QUESTION", "payload": {
                        "text": safe_bonus_preload if safe_bonus_preload else "[WARNING: PYTHON MEMORY HAS NO BONUS TEXT]", 
                        "answer": str(q_data.get('bonus_answer', '')),
                        "category": str(q_data.get('category', 'GENERAL')),
                        "options": q_data.get('bonus_options', []),
                        "visual": q_data.get('bonus_visual', False)
                    }})
                    
                    # TELL UI TO ONLY SHOW BONUS BUTTON
                    await self.outbound_queue.put({"type": "UI_STATE", "payload": {"show": "BONUS"}})
                    
                    action = await self.wait_for_moderator_action(["MANUAL_START_BONUS"])
                    action_type = action.type.name if hasattr(action.type, 'name') else str(action.type)
                    if action_type == "FORCE_RESET_STATE": continue 
                    elif action_type == "CHALLENGE":
                        self.log_event("CHALLENGE", "None", "Moderator", False, 0, "Bonus Dead", 0.0)
                        await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "⚠️ CHALLENGE! Clock paused. Edit scoresheet, then Start Next Tossup."}})
                        self.state.next_question()
                        self.current_q_idx += 1
                        continue

                    # HIDE BUTTONS WHILE READING/EVALUATING
                    await self.outbound_queue.put({"type": "UI_STATE", "payload": {"show": "NONE"}})

                    await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "🔊 Reading Bonus..."}})
                    
                    raw_bonus = str(q_data.get('bonus_text', '')).strip()
                    bonus_options = q_data.get('bonus_options', [])
                    bonus_options_spoken = " ".join(bonus_options) if bonus_options else ""
                    
                    bonus_text_to_read = f"Bonus, " + raw_bonus + "  " + bonus_options_spoken if raw_bonus else ""
                    
                    if self.use_audio and bonus_text_to_read:
                        await self.outbound_queue.put({"type": "START_READING", "payload": {"text": bonus_text_to_read}})
                    else:
                        self.inbound_queue.put_nowait(Event(type=EventType.TIMEOUT, payload={}))
                        
                    while True:
                        event = await self.inbound_queue.get()
                        evt_type = event.type.name if hasattr(event.type, 'name') else str(event.type)
                        if evt_type in ["EXPORT_CSV", "SAVE_CALIBRATION", "CALIBRATE_BASELINE", "PROCESS_FRAME", "PING", "UPDATE_STATUS", "PAUSE_MATCH", "ADJUST_SCORE", "EDIT_LOG_ENTRY", "CHALLENGE"]:
                            if evt_type == "CHALLENGE":
                                self.log_event("CHALLENGE", "None", "Moderator", False, 0, "Bonus Dead", 0.0)
                                await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "⚠️ CHALLENGE! Clock paused. Edit scoresheet, then Start Next Tossup."}})
                                self.state.next_question()
                                self.current_q_idx += 1
                                break 
                            if evt_type not in ["PING", "PAUSE_MATCH"]:
                                await self.process_admin_event(event)
                            continue
                        if evt_type == "READING_DONE":
                            break
                            
                    # Need to check if we broke out due to challenge during the read
                    if evt_type == "CHALLENGE":
                        continue
                    
                    self.state.transition_to(GameState.BONUS_CONFERRING) 
                    spoken_bonus = ""
                    
                    if self.use_audio:
                        await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "⏳ Conferring (20s). Buzz to answer!"}})
                        
                        start_bonus_time = asyncio.get_running_loop().time()
                        buzzed_in = False
                        challenge_triggered = False
                        
                        # --- CAPTAIN'S BUZZ / 20 SEC TIMEOUT LOGIC ---
                        while True:
                            elapsed = asyncio.get_running_loop().time() - start_bonus_time
                            remaining = 20.0 - elapsed
                            
                            if remaining <= 0:
                                break
                                
                            try:
                                reply = await asyncio.wait_for(self.inbound_queue.get(), timeout=remaining)
                                evt_type = reply.type.name if hasattr(reply.type, 'name') else str(reply.type)
                                
                                if evt_type == "BUZZ":
                                    buzzed_in = True
                                    break
                                elif evt_type == "CHALLENGE":
                                    challenge_triggered = True
                                    break
                                elif evt_type in ["EXPORT_CSV", "SAVE_CALIBRATION", "CALIBRATE_BASELINE", "PROCESS_FRAME", "PING", "UPDATE_STATUS", "PAUSE_MATCH", "ADJUST_SCORE", "EDIT_LOG_ENTRY"]:
                                    if evt_type not in ["PING", "PAUSE_MATCH"]:
                                        await self.process_admin_event(reply)
                            except asyncio.TimeoutError:
                                break
                                
                        if challenge_triggered:
                            self.log_event("CHALLENGE", "None", "Moderator", False, 0, "Bonus Dead", 0.0)
                            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "⚠️ CHALLENGE! Clock paused. Edit scoresheet, then Start Next Tossup."}})
                            self.state.next_question()
                            self.current_q_idx += 1
                            continue

                        # --- DYNAMIC LISTEN TIMEOUT (MIN 8 SECS OR REMAINING TIME) ---
                        elapsed_confer = asyncio.get_running_loop().time() - start_bonus_time
                        remaining_confer = max(0.0, 20.0 - elapsed_confer)
                        listen_time = min(8.0, remaining_confer)
                        
                        if listen_time > 0.5: # Only open mic if there is meaningful time left
                            current_sys_time = time.time()
                            await self.outbound_queue.put({
                                "type": "START_LISTENING", 
                                "payload": {"timeout": listen_time, "expires_at": current_sys_time + listen_time}
                            })
                            
                            try:
                                while True:
                                    reply = await asyncio.wait_for(self.inbound_queue.get(), timeout=listen_time + 4.0)
                                    evt_type = reply.type.name if hasattr(reply.type, 'name') else str(reply.type)
                                    
                                    if evt_type == "ANSWER_AUDIO":
                                        await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "⏳ Transcribing Bonus..."}})
                                        b64_audio = reply.payload.get("audio_data", "")
                                        if self.judge: spoken_bonus = await self.judge.transcribe_audio(b64_audio)
                                        await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": f"🗣️ Heard: '{spoken_bonus}'"}})
                                        break
                                    elif evt_type == "CHALLENGE":
                                        challenge_triggered = True
                                        break
                                    elif evt_type in ["EXPORT_CSV", "SAVE_CALIBRATION", "CALIBRATE_BASELINE", "PROCESS_FRAME", "PING", "UPDATE_STATUS", "PAUSE_MATCH", "ADJUST_SCORE", "EDIT_LOG_ENTRY"]:
                                        if evt_type not in ["PING", "PAUSE_MATCH"]:
                                            await self.process_admin_event(reply)
                            except asyncio.TimeoutError:
                                spoken_bonus = ""
                                
                        if challenge_triggered:
                            self.log_event("CHALLENGE", "None", "Moderator", False, 0, "Bonus Dead", 0.0)
                            await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "⚠️ CHALLENGE! Clock paused. Edit scoresheet, then Start Next Tossup."}})
                            self.state.next_question()
                            self.current_q_idx += 1
                            continue
                            
                    else:
                        await asyncio.sleep(1)
                        spoken_bonus = "Chloroplast"

                    self.state.transition_to(GameState.EVALUATING_BONUS) 
                    bonus_ans_text = str(q_data.get('bonus_answer', ''))
                    
                    if self.judge:
                        bonus_correct = await self.judge.evaluate_answer(spoken_bonus, bonus_ans_text, str(q_data.get('category', 'GENERAL')))
                    else:
                        bonus_correct = False
                    
                    self.state.apply_bonus_points(bonus_correct) 
                    if bonus_correct:
                        self.log_event("BONUS", bonus_earned_by, "Captain", True, 10, "Full Read", 0.0)
                        await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "✅ Bonus Correct! +10 points."}})
                        await self._speak_and_wait("That is correct.")
                    else:
                        self.log_event("BONUS", bonus_earned_by, "Captain", False, 0, "Full Read", 0.0)
                        await self.outbound_queue.put({"type": "UPDATE_STATUS", "payload": {"text": "❌ Bonus Incorrect."}})
                        await self._speak_and_wait(f"That is incorrect. The correct answer is {bonus_ans_text}.")
                        
                    await self.outbound_queue.put({"type": "UPDATE_SCORE", "payload": {"score_a": self.state.team_a_score, "score_b": self.state.team_b_score}})
                    
                self.state.next_question() 
                self.current_q_idx += 1
                await asyncio.sleep(2)

        except asyncio.CancelledError:
            pass
        finally:
            print("Shutting down game loop...")

def load_question_bank(file_path: str) -> list:
    if not file_path.startswith("questions/") and not file_path.startswith("questions\\"):
        file_path = os.path.join("questions", file_path)

    if not os.path.exists(file_path):
        print(f"\n❌ [FATAL ERROR]: FILE NOT FOUND: {file_path}")
        sys.exit(1)
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            bank = json.load(f)
            print(f"\n[DEBUG]: Successfully loaded {len(bank)} questions from '{file_path}'")
            return bank
    except json.JSONDecodeError as e:
        print(f"\n❌ [FATAL ERROR]: JSON FILE BROKEN: {e}")
        sys.exit(1)

async def main():
    parser = argparse.ArgumentParser(description="Agentic Moderator Backend")
    parser.add_argument("--set", type=str, default="m_round01_bank.json")
    parser.add_argument("--no-audio", action="store_true", help="Disable TTS and Mic")
    parser.add_argument("--use-camera", action="store_true", help="Enable OpenCV Vision")
    args = parser.parse_args()

    questions = load_question_bank(args.set)
    
    moderator = ScienceBowlModerator(
        use_audio=not args.no_audio, 
        use_camera=args.use_camera,
        initial_bank=questions 
    )

    tasks = [
        asyncio.create_task(moderator.ui.start_server()),
        asyncio.create_task(moderator.ui.update_ui_from_queue()),
        asyncio.create_task(moderator.run_game_loop()) 
    ]
    
    print("\n" + "="*50)
    print("🚀 [SYSTEM LIVE]: Backend and UI WebSocket are running!")
    print("👉 Open http://localhost:8080 in your web browser.")
    print("="*50 + "\n")
    
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    # Dynamically grab the port for Render deployment
    port = int(os.environ.get("PORT", 8080))
    
    print("==================================================")
    print(f"🚀 [SYSTEM LIVE]: Multi-Room Server booting on port {port}")
    print("==================================================")
    
    # Run the FastAPI app directly from the UI service
    uvicorn.run("services.ui_service:app", host="0.0.0.0", port=port)