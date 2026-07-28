import React, { useState, useRef, useEffect } from "react";
import axios from "axios";
import { 
  FolderPlus, UploadCloud, Send, User, Bot, 
  Loader2, Code2, CheckCircle2, FileCode2, 
  Copy, Check, FileText, Sparkles, RefreshCcw, ShieldAlert, BarChart3
} from "lucide-react";
import toast, { Toaster } from "react-hot-toast";
import Markdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";

const API = "http://127.0.0.1:5000";

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

function App() {
  const [projectId, setProjectId] = useState("");
  const [file, setFile] = useState(null);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  
  const chatEndRef = useRef(null);

  const SUGGESTED_PROMPTS = [
    "Explain the overall architecture",
    "Are there any security vulnerabilities?",
    "Suggest performance optimizations",
    "How can I improve the code quality?"
  ];

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const clearChat = () => {
    setMessages([{ role: "ai", content: "Chat cleared. What else would you like to know about your code?" }]);
  };

  const createProject = async () => {
    try {
      const res = await axios.post(`${API}/api/projects/create`);
      setProjectId(res.data.project_id);
      setUploadedFiles([]);
      toast.success("Project Created Successfully!");
      setMessages([{ role: "ai", content: "New project initialized. Upload some code and ask me anything!" }]);
    } catch (err) {
      toast.error("Project creation failed");
    }
  };

  const handleDragOver = (e) => e.preventDefault();
  const handleDrop = (e) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setFile(e.dataTransfer.files[0]);
    }
  };

  const uploadFile = async () => {
    if (!file) return toast.error("Please select a file first");
    if (!projectId) return toast.error("Please create a project first");

    setUploading(true);
    const formData = new FormData();
    formData.append("files", file);

    try {
      const res = await axios.post(`${API}/api/projects/${projectId}/upload`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success("File uploaded successfully");
      
      // Update files list from backend metadata if available
      const filesList = res.data.metadata?.files?.map(f => f.filename) || [...uploadedFiles, file.name];
      setUploadedFiles(filesList);
      setFile(null);
    } catch (err) {
      toast.error("Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const analyzeProject = async () => {
    if (!projectId) return toast.error("No active project");
    setAnalyzing(true);
    try {
      const res = await axios.get(`${API}/api/projects/${projectId}/analyze`);
      setMessages(prev => [
        ...prev,
        { role: "user", content: "Run full project architectural and security analysis." },
        { role: "ai", content: res.data.analysis }
      ]);
      toast.success("Project analysis complete!");
    } catch (err) {
      toast.error("Failed to analyze project");
    } finally {
      setAnalyzing(false);
    }
  };

  const askQuestion = async (textOverride = null) => {
    const currentQuestion = textOverride || question;
    if (!currentQuestion.trim()) return;
    if (!projectId) return toast.error("Please create a project or upload code first");

    setMessages((prev) => [...prev, { role: "user", content: currentQuestion }]);
    setQuestion("");
    setLoading(true);

    try {
      const res = await axios.post(`${API}/api/projects/${projectId}/ask`, {
        question: currentQuestion,
        history: messages.filter(m => m.role === "user" || m.role === "ai").map(m => ({
          role: m.role === "ai" ? "assistant" : "user",
          content: m.content
        }))
      });
      
      setMessages((prev) => [
        ...prev, 
        { role: "ai", content: res.data.answer, sources: res.data.sources }
      ]);
    } catch (err) {
      setMessages((prev) => [...prev, { role: "ai", content: "⚠️ Error getting response from server." }]);
      toast.error("Error getting response");
    } finally {
      setLoading(false);
    }
  };

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
                file ? "border-emerald-500 bg-emerald-500/10" : "border-slate-700 bg-slate-950/50 hover:border-slate-500"
              }`}
            >
              <input
                type="file"
                id="file-upload"
                className="hidden"
                onChange={(e) => setFile(e.target.files[0])}
              />
              <label htmlFor="file-upload" className="cursor-pointer flex flex-col items-center gap-2">
                {file ? <FileCode2 className="w-8 h-8 text-emerald-400" /> : <UploadCloud className="w-8 h-8 text-slate-500" />}
                <div className="text-xs text-slate-400">
                  {file ? <span className="text-slate-200 font-medium">{file.name}</span> : <span>Click or drag code file here</span>}
                </div>
              </label>
            </div>

            <button
              onClick={uploadFile}
              disabled={!file || uploading}
              className="w-full flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 font-medium py-2 px-4 rounded-lg transition-colors border border-slate-700 text-sm"
            >
              {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <UploadCloud className="w-4 h-4" />}
              {uploading ? "Ingesting Chunks..." : "Upload & Embed"}
            </button>

            {uploadedFiles.length > 0 && (
              <div className="mt-4">
                <h3 className="text-xs font-semibold text-slate-500 mb-2 uppercase">Indexed Files</h3>
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
            CodeWise RAG Assistant ({API.includes('5000') ? 'Ollama Connected' : ''})
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
              <div key={idx} className={`flex gap-4 max-w-4xl mx-auto ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
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
                    ) : (
                      <div className="prose prose-invert prose-emerald max-w-none">
                        <Markdown components={{ code: CodeBlock }}>{msg.content}</Markdown>
                      </div>
                    )}
                  </div>

                  {msg.sources && msg.sources.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-1">
                      {msg.sources.map((source, sIdx) => (
                        <div key={sIdx} className="flex items-center gap-1.5 text-[11px] bg-slate-800/80 text-slate-400 px-2 py-1 rounded border border-slate-700/50">
                          <FileText size={10} className="text-emerald-500" />
                          <span>{source.filename}</span>
                          <span className="text-slate-500">(Lines {source.lines})</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}

          {loading && (
            <div className="flex gap-4 max-w-4xl mx-auto">
              <div className="w-8 h-8 shrink-0 rounded-md bg-indigo-600 text-white flex items-center justify-center mt-1">
                <Bot className="w-5 h-5" />
              </div>
              <div className="px-5 py-4 rounded-2xl rounded-tl-none bg-slate-900/80 border border-slate-800 flex items-center gap-2">
                <Loader2 className="w-5 h-5 animate-spin text-emerald-500" />
                <span className="text-slate-400 text-sm animate-pulse">Querying vector database & generating answer...</span>
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
              <button
                onClick={() => askQuestion()}
                disabled={loading || !question.trim() || !projectId}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-700 text-slate-950 disabled:text-slate-500 rounded-lg transition-colors"
              >
                <Send className="w-5 h-5" />
              </button>
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