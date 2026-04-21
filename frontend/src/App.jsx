import React, { useEffect, useRef, useState } from "react";

const RAG_API = import.meta.env.VITE_API;

const SUGGESTIONS = [
  { q: "What was Apple's revenue last quarter?" },
  { q: "Did NVIDIA beat earnings estimates?" },
  { q: "What is Tesla's gross margin trend?" },
];

const MAX_HISTORY_TURNS = 8;

function nowTime() {
  return new Date().toLocaleTimeString("en-US", { hour12: false });
}

function buildHistoryPayload(messages) {
  return messages
    .filter((msg) => msg.role === "user" || msg.role === "assistant")
    .map((msg) => ({ role: msg.role, content: msg.content }))
    .slice(-MAX_HISTORY_TURNS);
}

export default function RAGChat() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [ingesting, setIngesting] = useState(false);

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const requestSeqRef = useRef(0);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleNewChat = () => {
    requestSeqRef.current += 1;
    setMessages([]);
    setQuestion("");
    setLoading(false);
    setIngesting(false);
    inputRef.current?.focus();
  };

  const handleIngest = async () => {
    if (ingesting || loading) return;
    setIngesting(true);

    const systemMsg = {
      role: "assistant",
      content: "SYSTEM: STARTING FULL DATA INGESTION PIPELINE...",
      timestamp: nowTime(),
    };
    setMessages((prev) => [...prev, systemMsg]);

    try {
      const response = await fetch(`${RAG_API}/rag/ingest`, {
        method: "POST",
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();

      let resultText = "SYSTEM: INGESTION COMPLETE.\n\nRESULTS:\n";
      if (data.ingested_chunks) {
        Object.entries(data.ingested_chunks).forEach(([source, count]) => {
          resultText += `  - ${source.toUpperCase()}: ${count === -1 ? "FAILED" : count + " chunks"}\n`;
        });
      }

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: resultText.trim(),
          timestamp: nowTime(),
        },
      ]);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          role: "error",
          content: `SYSTEM: INGESTION FAILURE: ${error.message}`,
          timestamp: nowTime(),
        },
      ]);
    } finally {
      setIngesting(false);
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!question.trim() || loading) return;

    const requestId = requestSeqRef.current + 1;
    requestSeqRef.current = requestId;

    const userMsg = {
      role: "user",
      content: question,
      timestamp: nowTime(),
    };

    const history = buildHistoryPayload(messages);

    setMessages((prev) => [...prev, userMsg]);
    setQuestion("");
    setLoading(true);

    try {
      const response = await fetch(`${RAG_API}/rag/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: userMsg.content,
          history,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();

      if (requestId !== requestSeqRef.current) {
        return;
      }

      let cleanAnswer = (data.answer || "").trim();
      cleanAnswer = cleanAnswer.replace(
        /\s*[\(\[]Passage\s*\d+(?:\s*(?:and|or|,)\s*Passage\s*\d+)*[\)\]]\s*/gi,
        " "
      );
      cleanAnswer = cleanAnswer.replace(
        /\s*as reported in Passage\s*\d+(?:\s*and\s*Passage\s*\d+)*\s*/gi,
        " "
      );

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: cleanAnswer,
          timestamp: nowTime(),
        },
      ]);
    } catch (error) {
      if (requestId !== requestSeqRef.current) {
        return;
      }

      setMessages((prev) => [
        ...prev,
        {
          role: "error",
          content: `PIPELINE FAILURE: ${error.message}`,
          timestamp: nowTime(),
        },
      ]);
    } finally {
      if (requestId === requestSeqRef.current) {
        setLoading(false);
        inputRef.current?.focus();
      }
    }
  };

  return (
    <div className="trm-chat-page">
      <div className="trm-statusbar">
        <span className="trm-status-title">FINANCIAL RAG ENGINE</span>
        <button
          type="button"
          className="trm-ingest-btn"
          onClick={handleIngest}
          disabled={ingesting || loading}
        >
          {ingesting ? "INGESTING..." : "INGEST"}
        </button>
        <button
          type="button"
          className="trm-new-chat-btn"
          onClick={handleNewChat}
          disabled={messages.length === 0 && !question && !loading && !ingesting}
        >
          NEW CHAT
        </button>
      </div>

      <div className="trm-chat-body">
        {messages.length === 0 ? (
          <div className="trm-chat-empty">
            <div className="trm-empty-title">RAG PIPELINE READY</div>
            <div className="trm-empty-sub">
              Query SEC filings, earnings reports and financial news.
              <br />
              Advanced retrieval · Hybrid search · Re-ranking · AI synthesis.
            </div>
            <div className="trm-chat-suggestions">
              {SUGGESTIONS.map((suggestion, index) => (
                <button
                  key={index}
                  className="trm-suggestion"
                  onClick={() => {
                    setQuestion(suggestion.q);
                    inputRef.current?.focus();
                  }}
                >
                  <span className="trm-suggestion-q">{suggestion.q}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="trm-messages">
            {messages.map((msg, index) => (
              <div key={index} className={`trm-msg trm-msg-${msg.role}`}>
                <div className="trm-msg-meta">
                  <span className="trm-msg-role">
                    {msg.role === "user" ? ">> USER" : msg.role === "error" ? "!! ERROR" : "<< ENGINE"}
                  </span>
                  <span className="trm-msg-time">{msg.timestamp}</span>
                </div>
                <div className="trm-msg-content">{msg.content}</div>
              </div>
            ))}

            {loading ? (
              <div className="trm-msg trm-msg-assistant">
                <div className="trm-msg-meta">
                  <span className="trm-msg-role">&lt;&lt; ENGINE</span>
                  <span className="trm-msg-status">RUNNING PIPELINE...</span>
                </div>
                <div className="trm-msg-typing">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            ) : null}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      <form className="trm-chat-input-bar" onSubmit={handleSubmit}>
        <span className="trm-prompt">&gt;&gt;</span>
        <input
          ref={inputRef}
          type="text"
          placeholder="ASK ABOUT FILINGS, EARNINGS, OR NEWS..."
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          className="trm-chat-question"
          disabled={loading}
          spellCheck={false}
        />
        <button type="submit" className="trm-search-btn" disabled={!question.trim() || loading}>
          {loading ? "PROCESSING..." : "SUBMIT"}
        </button>
      </form>
    </div>
  );
}
