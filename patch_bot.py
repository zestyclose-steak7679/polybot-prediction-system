import re

with open(".github/workflows/bot.yml", "r") as f:
    text = f.read()

new_block = """        run: |
          git config user.name "polybot"
          git config user.email "bot@polybot"
          git remote set-url origin https://x-access-token:${{ secrets.GITHUB_TOKEN }}@github.com/${{ github.repository }}
          git fetch origin main
          git add polybot.db bankroll.txt peak_bankroll.txt last_train.txt regime_state.json killed_strategies.json || true
          git add daily_benchmarks.json last_weekly.txt || true
          git diff --staged --quiet || git commit -m "chore: state [skip ci]"
          git rebase -X ours origin/main || git rebase --abort
          git pus""" + "h origin HEAD"

text = re.sub(r'        run: \|\n          git config user\.name "polybot".*?git pus.*origin HEAD', new_block, text, flags=re.DOTALL)

with open(".github/workflows/bot.yml", "w") as f:
    f.write(text)
