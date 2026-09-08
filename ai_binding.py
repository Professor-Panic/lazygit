import ai
("g", "ai_commit", "AI-suggest commit"),

async def action_ai_commit(self):
   diff_text=getStagedDiff()
   if not diff_text.strip():
      self.notify("Nothing staged to summarize.", title="AI commit", severity="warning")
      return

   log_display = self.query_one(CommandLogDisplay)
   log_display.log("AI: generating commit message...", "Running...", "", 0)


   try:
      result = await asyncio.to_thread(ai.suggest_commit_message, diff_text)
      log_display.log("AI: generated", result["full"], "", 0)
      self.push_screen(CommitModal(), self._handle_ai_commit_result)
      self._pending_ai_message = result["full"]
   except Exception as e:
      self.notify(f"AI suggestion failed: {e}", title="AI commit", severity="warning")


async def _handle_ai_commit_result(self,message):
   if not message:
      return
   stdout, stderr, returncode = await asyncio.tothread(doCommit, message)
   self.query_one(CommandLogDisplay).log(f'git commit -m "{message}',stdout, stderr, returncode)
   await self.query_one(FileDisplay).refresh_display(force=True)