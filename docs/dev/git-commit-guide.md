# Commit 指南

工作流第 6 步「提交」時使用。目標是**看得懂、判斷得出 commit 訊息對不對**，不是背格式或自己寫英文。

## 格式

```
類型(範圍): 摘要                ← 標題，一行，英文
                                ← 空一行
- 改了什麼、為什麼              ← 內文，條列，暫時可以用中文
                                ← 空一行
Co-Authored-By: ...             ← 尾註（和 Agent 一起完成時）
```

| 類型 | 意思 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修 bug |
| `docs` | 只改文件 |
| `test` | 只改測試 |
| `refactor` | 改寫法，不改行為 |
| `chore` | 雜事，不影響程式（例如套件鎖定檔） |

- **範圍**可省略，寫改到的部分，例如 `fix(render):`
- **摘要**用原形動詞（`add`，不寫 `added`）、小寫開頭、不加句號、50～72 字元內
- 一個 commit 只做一類事；新功能和修 bug 混在一起時，考慮拆成兩個 commit

## 學習階段

| 階段 | 使用者做什麼 | Agent 做什麼 | 進入下一階段 |
|---|---|---|---|
| 1. 選類型 | 看完這次修改的摘要，回答一個詞：這次是哪個類型？ | 寫完整訊息，說明選對或選錯的原因 | 連續 3 次選對 |
| 2. 用中文說重點 | 用中文寫一句「這次改了什麼」 | 依這句話寫英文標題並說明句型；內文由 Agent 寫 | — |

- 使用者說「**趕時間**」：該次由 Agent 寫完整訊息，不計入進度
- 覺得太難可以隨時退回上一階段
- 目前的階段和連續次數記在 Agent 的 memory 裡

## 每次提交的流程（給 Agent）

1. 第一則訊息：列出這次修改的白話摘要和 `git add`／`git status` 指令，附上該階段的問題
2. 使用者回答後：回饋答案，把訊息寫進 scratchpad 的檔案，**在對話中列出完整訊息並逐行附中文說明**，再給 `git commit -F <檔案>` 和 `git push`
3. 指令一條一行；使用者正從 cmd 改用 Git Bash，路徑用 Git Bash 寫法（`/c/Users/...`）
4. 更新 memory 裡的階段和連續次數

## 句型表（讀懂訊息用，不用背）

| 英文 | 意思 | 例子 |
|---|---|---|
| `add X` | 新增 X | `add --sub-lang option` |
| `add X to Y` | 在 Y 裡新增 X | `add revision log to spec template` |
| `fix X` | 修正 X | `fix subtitle path on Windows` |
| `fix X when Y` | 在 Y 的情況下修正 X | `fix concat when path has non-ASCII characters` |
| `remove X` | 移除 X | `remove unused helper` |
| `update X` | 更新 X（內容調整） | `update install guide` |
| `use Y for X` | X 改用 Y | `use UTF-8 for EDL files` |
| `rename X to Y` | X 改名為 Y | `rename edit dir to edit_openai` |
| `move X to Y` | 把 X 移到 Y | `move templates to docs/dev` |
| `support X` | 支援 X | `support OpenAI whisper-1` |
| `warn when X` | 在 X 時發出警告 | `warn when transcript looks Chinese` |
| `X; Y` | 同一個 commit 做了兩件事 | `add zh-tw captions; fix Windows paths` |
