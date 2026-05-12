# Token 大幅減少技巧指南

> 整合 2026 年業界最佳實踐，依實施難度與節省效果排列。

---

## 快速參考表

| 方法 | 節省比例 | 難度 | 適用情境 |
|------|---------|------|---------|
| Prompt Caching | **60–90%** | 低 | 重複系統提示、長對話 |
| 對話歷史壓縮 | **80–90%** | 中 | 長對話、聊天機器人 |
| Batch API | **50%** | 低 | 非即時批量任務 |
| RAG 優化 | **40–70%** | 中 | 知識庫查詢 |
| 簡潔提示 | **30–40%** | 低 | 所有情境 |
| Prompt Compression | **20–40%** | 高 | 長文檔、複雜內容 |
| 模型路由 | **20–50%** | 低 | 多任務應用 |
| Fine-tuning | **50–70%** | 高 | 長期重複任務 |

---

## 第一優先：可立即實施（低難度）

### 1. Prompt Caching（Claude API 官方）

**節省：60–90%**

將穩定不變的 system prompt 或長文檔標記為可快取，後續呼叫只需支付 10% token 成本。

```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    system=[
        {
            "type": "text",
            "text": "你是一個台股分析助理...",
            "cache_control": {"type": "ephemeral"}  # 標記快取
        }
    ],
    messages=[{"role": "user", "content": "分析 2330"}]
)
```

**成本結構：**
- 快取寫入：1.25x 基礎價格
- 快取讀取：0.10x 基礎價格（節省 90%）
- TTL：5 分鐘，每次命中自動刷新
- 最低長度：Sonnet/Haiku = 1,024 tokens；Opus = 4,096 tokens

**使用原則：**
- 將 system prompt 放最前、標記快取
- 變動內容（user input）放最後，不標記
- 100% 相同才能命中快取（包含空格）

---

### 2. Batch API（非即時任務節省 50%）

**節省：50%**

```python
import anthropic

client = anthropic.Anthropic()

# 建立批次請求
batch = client.messages.batches.create(
    requests=[
        {
            "custom_id": f"stock_{ticker}",
            "params": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": f"分析 {ticker} 的技術訊號"}]
            }
        }
        for ticker in ["2330", "2317", "2454"]
    ]
)

print(f"批次 ID: {batch.id}")  # 輪詢或 webhook 取結果
```

**適用：** 回測報告、每日掃描、批量評估

---

### 3. 輸出格式限制

**節省：15–25%**

在 prompt 中明確限制輸出：

```
# 好的做法
回應格式：
- 只輸出 JSON，不要任何說明文字
- 欄位：signal (buy/sell/hold), confidence (0-1), reason (15字內)

# 避免
"請詳細分析並提供完整說明..."
```

---

### 4. 模型選擇優化

**節省：20–50%**

| 任務類型 | 建議模型 |
|---------|---------|
| 簡單分類、快速查詢 | `claude-haiku-4-5-20251001` |
| 一般分析、程式碼 | `claude-sonnet-4-6` |
| 複雜推理、架構設計 | `claude-opus-4-7` |

```python
def select_model(task_complexity: str) -> str:
    return {
        "simple": "claude-haiku-4-5-20251001",
        "standard": "claude-sonnet-4-6",
        "complex": "claude-opus-4-7"
    }[task_complexity]
```

---

## 第二優先：中期優化（中難度）

### 5. 對話歷史漸進式壓縮

**節省：80–90%**

保留最近 N 輪完整對話，舊內容自動壓縮為摘要：

```python
def compress_history(messages: list, keep_recent: int = 6) -> list:
    if len(messages) <= keep_recent:
        return messages

    old_messages = messages[:-keep_recent]
    recent_messages = messages[-keep_recent:]

    # 用小模型壓縮舊對話
    summary_response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": f"用100字以內摘要以下對話重點：\n{format_messages(old_messages)}"
            }
        ]
    )

    summary_msg = {
        "role": "assistant",
        "content": f"[對話摘要] {summary_response.content[0].text}"
    }

    return [summary_msg] + recent_messages
```

---

### 6. RAG：只傳必要片段

**節省：40–70%**

不傳整份文件，只傳語義最相關的 top-k 段落：

```python
from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

def retrieve_relevant_chunks(query: str, documents: list[str], top_k: int = 3) -> list[str]:
    query_emb = model.encode([query])
    doc_embs = model.encode(documents)
    scores = np.dot(query_emb, doc_embs.T)[0]
    top_indices = np.argsort(scores)[-top_k:][::-1]
    return [documents[i] for i in top_indices]

# 只傳相關片段給 Claude
relevant = retrieve_relevant_chunks(user_query, all_chunks, top_k=3)
context = "\n---\n".join(relevant)
```

---

### 7. System Prompt 精簡原則

**節省：30–40%**

```markdown
# 壞（冗長）
你是一個非常專業且經驗豐富的台股分析師，擁有多年的投資經驗，
你非常擅長分析籌碼面、技術面和基本面，你會提供詳細而全面的分析...

# 好（精簡）
角色：台股分析師
專長：籌碼面、技術面
輸出：JSON格式，無額外說明
```

**規則：**
- System prompt 控制在 800 字以內
- 移除「你是一個非常...」類型的冗餘描述
- 指令按重要性排序，核心規則放最前
- 用條列取代長段落

---

## 第三優先：長期方案（高難度）

### 8. Prompt Compression（LLMLingua）

**節省：20–40%，可達 4–20x 壓縮比**

使用 Microsoft LLMLingua 自動壓縮長文本：

```bash
pip install llmlingua
```

```python
from llmlingua import PromptCompressor

compressor = PromptCompressor(
    model_name="microsoft/llmlingua-2-xlm-roberta-large-meetingbank",
    use_llmlingua2=True,
    device_map="cpu"
)

compressed = compressor.compress_prompt(
    long_context,
    rate=0.5,        # 壓縮到 50% token
    force_tokens=["分析", "買入", "賣出"]  # 強制保留的關鍵詞
)

print(f"原始: {compressed['origin_tokens']} tokens")
print(f"壓縮後: {compressed['compressed_tokens']} tokens")
```

---

### 9. Fine-tuning（長期重複任務）

**節省：50–70%**

對特定任務微調後，不再需要長篇 few-shot 示例：

```python
# 微調前：需要 5 個 few-shot 示例 ≈ 2000 tokens
# 微調後：零樣本即可，system prompt 降至 100 tokens

# Anthropic Fine-tuning API（需申請）
fine_tuning_job = client.fine_tuning.jobs.create(
    model="claude-haiku-4-5-20251001",
    training_file="training_data.jsonl",
    hyperparameters={"n_epochs": 3}
)
```

**適用：** 每天重複執行相同格式分析的任務

---

## Claude Code 專屬技巧

### /btw 指令

提問不進入對話歷史，不消耗 context window：

```
/btw 這個函數的時間複雜度是多少？
```

### CLAUDE.md 結構優化

```
.claude/
  rules/
    always.md      # 所有場景載入（精簡！）
    python.md      # 只在 .py 檔案載入
    trading.md     # 只在交易相關檔案載入
```

在 `settings.json` 設定條件載入，避免每次載入所有規則。

### 自動 Context Compaction

```bash
# 在 context 達 95% 前自動壓縮
export CLAUDE_CODE_AUTO_COMPACT_WINDOW=200000
```

---

## 本專案適用建議

針對 `retail_flow_swing` 交易系統：

1. **每日掃描腳本** → 改用 Batch API（節省 50%）
2. **策略分析 system prompt** → 加入 `cache_control`（節省 60–90%）
3. **回測報告生成** → 限制輸出為 JSON，用 Haiku 模型
4. **長對話 debug session** → 每 10 輪壓縮一次歷史

---

## 參考資源

- [Anthropic Prompt Caching 文件](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Anthropic Batch Processing 文件](https://platform.claude.com/docs/zh-TW/build-with-claude/batch-processing)
- [Microsoft LLMLingua GitHub](https://github.com/microsoft/LLMLingua)
- [Redis LLM Token Optimization Guide](https://redis.io/blog/llm-token-optimization-speed-up-apps/)
