import React, { useState, useRef, useEffect } from "react";
import axios from "axios";
import { 
  FolderPlus, UploadCloud, Send, User, Bot, 
  Loader2, Code2, CheckCircle2, FileCode2, 
  Copy, Check, FileText, Sparkles, RefreshCcw, ShieldAlert, BarChart3,
  FolderOpen, Files, Link2, Square, GitBranch
} from "lucide-react";
import {
  fetchUploadRules, entriesFromDrop, entriesFromFileList, filterEntries, uploadEntries
} from "./lib/uploads";
import { streamSSE } from "./lib/stream";
import toast, { Toaster } from "react-hot-toast";
import Markdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";

const API = "http://127.0.0.1:8000";

const CodeBlock = ({ node, inline, className, children, ...props }) => {
  const match = /language-(\w+)/.exec(className || "");
  const [copied, setCopied] = useState(false);
  const codeString = String(children).replace(/\n$/, "");

  const handleCopy = () => {
    navigator.clipboard.writeText(codeString);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!inline && match) {
    return (
      <div className="relative group rounded-lg overflow-hidden my-4 border border-slate-700 shadow-lg bg-[#1E1E1E]">
        <div className="flex items-center justify-between px-4 py-2 bg-slate-800/50 border-b border-slate-700">
          <span className="text-xs font-mono text-slate-400">{match[1]}</span>
          <button
            onClick={handleCopy}
            className="text-slate-400 hover:text-emerald-400 transition-colors flex items-center gap-1.5 bg-slate-800 px-2 py-1 rounded-md text-xs"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
            {copied ? "Copied!" : "Copy"}
          </button>
        </div>
        <SyntaxHighlighter
          {...props}
          style={vscDarkPlus}
          language={match[1]}
          PreTag="div"
          customStyle={{ margin: 0, padding: "1.5rem", background: "transparent" }}
        >
          {codeString}
        </SyntaxHighlighter>
      </div>
    );
  }
  return (
    <code {...props} className="bg-slate-800 text-emerald-400 px-1.5 py-0.5 rounded font-mono text-sm">
      {children}
    </code>
  );
};

let nextMessageId = 1;
const newId = () => nextMessageId++;

function summarize({ indexed, skipped, failed }) {
  const parts = [`Indexed ${indexed} file${indexed === 1 ? "" : "s"}`];
  if (skipped) parts.push(`skipped ${skipped}`);
  if (failed) parts.push(`${failed} failed`);
  return parts.join(" · ");
}

function App() {
  const [projectId, setProjectId] = useState("");
  const [pending, setPending] = useState([]); // [{ file, path }] waiting to be uploaded
  const [pendingSkipped, setPendingSkipped] = useState(0);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [githubUrl, setGithubUrl] = useState("");
  const [importing, setImporting] = useState(false);
  const [rules, setRules] = useState(null);

  const chatEndRef = useRef(null);
  const abortRef = useRef(null);

  const SUGGESTED_PROMPTS = [
    "Explain the overall architecture",
    "Are there any security vulnerabilities?",
    "Suggest performance optimizations",
    "How can I improve the code quality?"
  ];

  useEffect(() => {
    fetchUploadRules(API).then(setRules);
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, analyzing]);

  const clearChat = () => {
    setMessages([{ id: newId(), role: "ai", content: "Chat cleared. What else would you like to know about your code?" }]);
  };

  const createProject = async () => {
    try {
      const res = await axios.post(`${API}/api/projects/create`);
      setProjectId(res.data.project_id);
      setUploadedFiles([]);
      toast.success("Project Created Successfully!");
      setMessages([{ id: newId(), role: "ai", content: "New project initialized. Upload some code and ask me anything!" }]);
    } catch (err) {
      toast.error("Project creation failed");
    }
  };

  const selectEntries = async (entries) => {
    const activeRules = rules || (await fetchUploadRules(API));
    const { kept, skipped } = filterEntries(entries, activeRules);
    setPending(kept);
    setPendingSkipped(skipped);
    if (kept.length === 0 && skipped > 0) toast.error(`No supported files (${skipped} skipped)`);
  };

  const handleDragOver = (e) => e.preventDefault();
  const handleDrop = async (e) => {
    e.preventDefault();
    const activeRules = rules || (await fetchUploadRules(API));
    selectEntries(await entriesFromDrop(e.dataTransfer, activeRules));
  };

  const applyUploadResult = (result) => {
    const filesList = result.metadata?.files?.map(f => f.filename);
    if (filesList) setUploadedFiles(filesList);
    if (result.indexed > 0) toast.success(summarize(result));
    else toast.error(summarize(result));
    if (result.failed > 0) console.warn("Failed uploads:", result.failures);
  };

  const uploadFile = async () => {
    if (pending.length === 0) return toast.error("Please select files first");
    if (!projectId) return toast.error("Please create a project first");

    setUploading(true);
    try {
      const activeRules = rules || (await fetchUploadRules(API));
      const result = await uploadEntries(API, projectId, pending, activeRules, (done, total) =>
        setUploadProgress(total > 1 ? `Uploading batch ${done}/${total}...` : "Ingesting chunks...")
      );
      applyUploadResult(result);
      setPending([]);
      setPendingSkipped(0);
    } catch (err) {
      toast.error(err.response?.data?.error || "Upload failed");
    } finally {
      setUploading(false);
      setUploadProgress("");
    }
  };

  const importGithub = async () => {
    if (!projectId) return toast.error("Please create a project first");
    if (!githubUrl.trim()) return;
    setImporting(true);
    try {
      const res = await axios.post(`${API}/api/projects/${projectId}/import/github`, { url: githubUrl.trim() });
      applyUploadResult({ ...res.data.summary, metadata: res.data.metadata, failures: [] });
      setGithubUrl("");
    } catch (err) {
      toast.error(err.response?.data?.error || "GitHub import failed");
    } finally {
      setImporting(false);
    }
  };

  const analyzeProject = async () => {
    if (!projectId) return toast.error("No active project");
    setAnalyzing(true);
    try {
      const res = await axios.get(`${API}/api/projects/${projectId}/analyze`);
      setMessages(prev => [
        ...prev,
        { id: newId(), role: "user", content: "Run full project architectural and security analysis." },
        { id: newId(), role: "ai", content: res.data.analysis }
      ]);
      toast.success("Project analysis complete!");
    } catch (err) {
      toast.error("Failed to analyze project");
    } finally {
      setAnalyzing(false);
    }
  };

  const updateMessage = (id, update) =>
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...update(m) } : m)));

  const askQuestion = async (textOverride = null) => {
    const currentQuestion = textOverride || question;
    if (!currentQuestion.trim()) return;
    if (!projectId) return toast.error("Please create a project or upload code first");

    const history = messages
      .filter(m => (m.role === "user" || m.role === "ai") && m.content && !m.error)
      .map(m => ({ role: m.role === "ai" ? "assistant" : "user", content: m.content }));
    const answerId = newId();
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: "user", content: currentQuestion },
      { id: answerId, role: "ai", content: "", sources: [], streaming: true },
    ]);
    setQuestion("");
    setLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamSSE(`${API}/api/projects/${projectId}/ask/stream`, { question: currentQuestion, history }, {
        signal: controller.signal,
        onEvent: (event, data) => {
          if (event === "sources") updateMessage(answerId, () => ({ sources: data.sources }));
          else if (event === "token") updateMessage(answerId, (m) => ({ content: m.content + data.content }));
          else if (event === "error") throw new Error(data.error);
        },
      });
      updateMessage(answerId, () => ({ streaming: false }));
    } catch (err) {
      if (err.name === "AbortError") {
        updateMessage(answerId, (m) => ({ streaming: false, content: (m.content || "") + "\n\n_(stopped)_" }));
      } else {
        updateMessage(answerId, (m) => ({
          streaming: false,
          error: !m.content,
          content: (m.content ? m.content + "\n\n" : "") + `⚠️ ${err.message || "Error getting response from server."}`,
        }));
        toast.error("Error getting response");
      }
    } finally {
      abortRef.current = null;
      setLoading(false);
    }
  };

  const stopAnswer = () => abortRef.current?.abort();

  return (
    <div className="flex h-screen bg-slate-950 text-slate-200 font-sans overflow-hidden">
      <Toaster position="top-right" toastOptions={{ style: { background: '#1e293b', color: '#fff', border: '1px solid #334155' } }} />

      {/* LEFT SIDEBAR */}
      <aside className="w-80 bg-slate-900 border-r border-slate-800 flex flex-col shadow-xl z-10">
        <div className="p-6 flex-1 flex flex-col gap-6 overflow-y-auto">
          
          <div className="flex items-center gap-3 text-emerald-400">
            <Code2 className="w-8 h-8" />
            <h1 className="text-2xl font-bold text-slate-100 tracking-tight">CodeWise</h1>
          </div>

          {/* 1. Workspace Control */}
          <div className="space-y-3">
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-widest">1. Workspace</h2>
            <button
              onClick={createProject}
              className="w-full flex items-center justify-center gap-2 bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-medium py-2.5 px-4 rounded-lg transition-colors shadow-lg shadow-emerald-500/20"
            >
              <FolderPlus className="w-5 h-5" />
              {projectId ? "New Project" : "Create Project"}
            </button>
            
            {projectId && (
              <div className="bg-slate-950 border border-slate-800 p-3 rounded-lg space-y-2 text-sm">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />
                  <span className="text-slate-300 font-medium">Project Active</span>
                </div>
                <button
                  onClick={analyzeProject}
                  disabled={analyzing || uploadedFiles.length === 0}
                  className="w-full mt-2 flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white py-2 rounded text-xs font-medium transition-colors"
                >
                  {analyzing ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />}
                  {analyzing ? "Analyzing..." : "Generate AI Code Audit"}
                </button>
              </div>
            )}
          </div>

          <div className="h-px bg-slate-800 w-full" />

          {/* 2. File Knowledge Base */}
          <div className="space-y-3 flex-1">
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-widest">2. Knowledge Base</h2>
            
            <div
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              className={`border-2 border-dashed rounded-xl p-5 text-center transition-all ${
                pending.length ? "border-emerald-500 bg-emerald-500/10" : "border-slate-700 bg-slate-950/50 hover:border-slate-500"
              }`}
            >
              <input
                type="file"
                id="file-upload"
                multiple
                className="hidden"
                onChange={(e) => { selectEntries(entriesFromFileList(e.target.files)); e.target.value = ""; }}
              />
              <input
                type="file"
                id="folder-upload"
                webkitdirectory=""
                directory=""
                className="hidden"
                onChange={(e) => { selectEntries(entriesFromFileList(e.target.files)); e.target.value = ""; }}
              />
              <div className="flex flex-col items-center gap-2">
                {pending.length ? <FileCode2 className="w-8 h-8 text-emerald-400" /> : <UploadCloud className="w-8 h-8 text-slate-500" />}
                <div className="text-xs text-slate-400">
                  {pending.length === 1 ? (
                    <span className="text-slate-200 font-medium">{pending[0].path}</span>
                  ) : pending.length > 1 ? (
                    <span className="text-slate-200 font-medium">{pending.length} files ready</span>
                  ) : (
                    <span>Drag files, a folder or a .zip here</span>
                  )}
                  {pendingSkipped > 0 && (
                    <span className="block text-slate-500 mt-0.5">{pendingSkipped} unsupported or ignored files left out</span>
                  )}
                </div>
                <div className="flex gap-2 mt-1">
                  <label htmlFor="file-upload" className="cursor-pointer flex items-center gap-1 text-[11px] bg-slate-800 hover:bg-slate-700 text-slate-300 px-2 py-1 rounded border border-slate-700">
                    <Files size={12} /> Files / .zip
                  </label>
                  <label htmlFor="folder-upload" className="cursor-pointer flex items-center gap-1 text-[11px] bg-slate-800 hover:bg-slate-700 text-slate-300 px-2 py-1 rounded border border-slate-700">
                    <FolderOpen size={12} /> Folder
                  </label>
                </div>
              </div>
            </div>

            <button
              onClick={uploadFile}
              disabled={pending.length === 0 || uploading}
              className="w-full flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 font-medium py-2 px-4 rounded-lg transition-colors border border-slate-700 text-sm"
            >
              {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <UploadCloud className="w-4 h-4" />}
              {uploading ? (uploadProgress || "Ingesting Chunks...") : "Upload & Embed"}
            </button>

            <div className="flex gap-2">
              <div className="relative flex-1">
                <Link2 className="w-4 h-4 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="github.com/owner/repo"
                  value={githubUrl}
                  onChange={(e) => setGithubUrl(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") importGithub(); }}
                  disabled={importing}
                  className="w-full bg-slate-950 border border-slate-700 focus:border-emerald-500 text-slate-200 text-xs rounded-lg pl-8 pr-2 py-2 disabled:opacity-50"
                />
              </div>
              <button
                onClick={importGithub}
                disabled={importing || !githubUrl.trim()}
                className="flex items-center gap-1 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 text-xs font-medium px-3 rounded-lg border border-slate-700"
              >
                {importing ? <Loader2 className="w-4 h-4 animate-spin" /> : "Import"}
              </button>
            </div>

            {uploadedFiles.length > 0 && (
              <div className="mt-4">
                <h3 className="text-xs font-semibold text-slate-500 mb-2 uppercase">Indexed Files ({uploadedFiles.length})</h3>
                <ul className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
                  {uploadedFiles.map((f, i) => (
                    <li key={i} className="flex items-center gap-2 text-xs text-slate-300 bg-slate-950 p-2 rounded border border-slate-800">
                      <FileText size={12} className="text-emerald-500 shrink-0" />
                      <span className="truncate">{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* MAIN CHAT AREA */}
      <main className="flex-1 flex flex-col relative bg-slate-950">
        
        <header className="h-14 border-b border-slate-800 bg-slate-900/50 backdrop-blur-sm flex items-center justify-between px-6 z-10">
          <div className="text-sm font-medium text-slate-300 flex items-center gap-2">
            <Sparkles size={16} className="text-emerald-400" />
            CodeWise RAG Assistant ({API.includes('8000') ? 'Ollama Connected' : ''})
          </div>
          {messages.length > 1 && (
            <button 
              onClick={clearChat}
              className="flex items-center gap-2 text-xs text-slate-400 hover:text-slate-200 bg-slate-800 hover:bg-slate-700 px-3 py-1.5 rounded-md transition-colors border border-slate-700"
            >
              <RefreshCcw size={12} /> Clear Chat
            </button>
          )}
        </header>

        <div className="flex-1 overflow-y-auto p-4 sm:p-8 space-y-6">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-500 gap-4">
              <Bot className="w-16 h-16 opacity-20" />
              <p className="text-lg">Create a project and upload your code to query chunks via vector search.</p>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div key={msg.id ?? idx} className={`flex gap-4 max-w-4xl mx-auto ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
                <div className={`w-8 h-8 shrink-0 rounded-md flex items-center justify-center mt-1 ${
                  msg.role === "user" ? "bg-emerald-600 text-white" : "bg-indigo-600 text-white shadow-lg shadow-indigo-500/20"
                }`}>
                  {msg.role === "user" ? <User className="w-5 h-5" /> : <Bot className="w-5 h-5" />}
                </div>

                <div className={`flex flex-col gap-2 max-w-[85%] ${msg.role === "user" ? "items-end" : "items-start"}`}>
                  <div className={`px-5 py-4 rounded-2xl text-sm sm:text-base leading-relaxed shadow-sm ${
                    msg.role === "user" 
                      ? "bg-slate-800 text-slate-100 rounded-tr-none border border-slate-700" 
                      : "bg-slate-900/80 text-slate-200 rounded-tl-none border border-slate-800 backdrop-blur-sm"
                  }`}>
                    {msg.role === "user" ? (
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    ) : msg.streaming && !msg.content ? (
                      <div className="flex items-center gap-2">
                        <Loader2 className="w-5 h-5 animate-spin text-emerald-500" />
                        <span className="text-slate-400 text-sm animate-pulse">Searching your code...</span>
                      </div>
                    ) : (
                      <div className="prose prose-invert prose-emerald max-w-none">
                        <Markdown components={{ code: CodeBlock }}>{msg.content}</Markdown>
                      </div>
                    )}
                  </div>

                  {msg.sources && msg.sources.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-1">
                      {msg.sources.map((source, sIdx) => (
                        <div
                          key={sIdx}
                          title={source.matched_by?.includes("graph") ? "Found via code relationships (calls/imports)" : undefined}
                          className="flex items-center gap-1.5 text-[11px] bg-slate-800/80 text-slate-400 px-2 py-1 rounded border border-slate-700/50"
                        >
                          {source.matched_by?.includes("graph")
                            ? <GitBranch size={10} className="text-indigo-400" />
                            : <FileText size={10} className="text-emerald-500" />}
                          <span>{source.filename}</span>
                          <span className="text-slate-500">(Lines {source.lines})</span>
                          {source.symbol && <span className="text-slate-500 font-mono truncate max-w-[12rem]">{source.symbol}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}

          {analyzing && (
            <div className="flex gap-4 max-w-4xl mx-auto">
              <div className="w-8 h-8 shrink-0 rounded-md bg-indigo-600 text-white flex items-center justify-center mt-1">
                <Bot className="w-5 h-5" />
              </div>
              <div className="px-5 py-4 rounded-2xl rounded-tl-none bg-slate-900/80 border border-slate-800 flex items-center gap-2">
                <Loader2 className="w-5 h-5 animate-spin text-emerald-500" />
                <span className="text-slate-400 text-sm animate-pulse">Analyzing the whole project (this can take a few minutes)...</span>
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        <div className="p-4 bg-slate-900 border-t border-slate-800 shadow-2xl z-10">
          <div className="max-w-4xl mx-auto flex flex-col gap-3">
            
            {messages.length <= 1 && projectId && uploadedFiles.length > 0 && (
              <div className="flex flex-wrap gap-2 justify-center mb-2">
                {SUGGESTED_PROMPTS.map((prompt, i) => (
                  <button 
                    key={i}
                    onClick={() => askQuestion(prompt)}
                    className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 rounded-full px-3 py-1.5 transition-colors"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            )}

            <div className="relative flex items-center">
              <textarea
                placeholder={uploadedFiles.length > 0 ? "Ask a question about your code..." : "Upload code to start asking questions..."}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); askQuestion(); } }}
                disabled={loading || !projectId}
                className="w-full bg-slate-950 border border-slate-700 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 text-slate-200 rounded-xl pl-4 pr-14 py-4 resize-none h-[56px] min-h-[56px] shadow-inner transition-all disabled:opacity-50"
                rows={1}
              />
              {loading ? (
                <button
                  onClick={stopAnswer}
                  title="Stop generating"
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg transition-colors"
                >
                  <Square className="w-5 h-5" />
                </button>
              ) : (
                <button
                  onClick={() => askQuestion()}
                  disabled={!question.trim() || !projectId}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-700 text-slate-950 disabled:text-slate-500 rounded-lg transition-colors"
                >
                  <Send className="w-5 h-5" />
                </button>
              )}
            </div>
            <p className="text-center text-xs text-slate-500 font-medium">
              Shift + Enter for new line • Enter to send
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;