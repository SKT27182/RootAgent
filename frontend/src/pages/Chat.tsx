import { useState, useEffect, useRef } from 'react'
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { Card } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Textarea } from "@/components/ui/textarea"
import { Separator } from "@/components/ui/separator"
import type { Message as MessageType } from "@/types"
import {
  getSessions,
  deleteSession,
  getHistory,
  listArtifacts,
  uploadArtifact,
  deleteArtifact,
  getArtifactDownloadUrl,
  type ArtifactItem,
} from "@/api"
import { Trash2, Copy, Send, Plus, Loader2, Sun, Moon, Menu, Settings2, X, Paperclip, ImagePlus } from "lucide-react"
import { cn } from "@/lib/utils"
import { normalizeHistoryMessages } from "@/lib/parse-history"
import { ChatMessageBubble, shouldHideMessage } from "@/components/ChatMessageBubble"

import { useAuth } from "@/lib/auth-context";

export default function Chat() {
  const { user, logout } = useAuth();
  const userId = user?.id || "anonymous";
  const [sessions, setSessions] = useState<string[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<MessageType[]>([])
  const [input, setInput] = useState("")
  const [useReasoning, setUseReasoning] = useState(true)
  const [showReasoning, setShowReasoning] = useState(true)
  const [isStreaming, setIsStreaming] = useState(false)
  
  // Theme state
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')
  
  // Mobile sidebar states
  const [isLeftSidebarOpen, setIsLeftSidebarOpen] = useState(false)
  const [isRightSidebarOpen, setIsRightSidebarOpen] = useState(false)

  const scrollRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const [csvFile, setCsvFile] = useState<{name: string, content: string} | null>(null)
  const [images, setImages] = useState<{name: string, base64: string}[]>([])
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([])
  const [selectedArtifactIds, setSelectedArtifactIds] = useState<string[]>([])

  const appendStepMessage = (msg: MessageType) => {
    setMessages((prev) => [...prev, msg])
  }

  // Handle Theme Change
  useEffect(() => {
    const root = window.document.documentElement
    root.classList.remove('light', 'dark')
    root.classList.add(theme)
  }, [theme])

  // Fetch sessions on mount and when userId changes
  useEffect(() => {
    if (userId !== "anonymous") {
        refreshSessions();
    }
  }, [userId])

  // Fetch history when session changes
  useEffect(() => {
    if (currentSessionId) {
      loadHistory(currentSessionId);
      loadArtifacts(currentSessionId);
      setIsLeftSidebarOpen(false);
    } else {
      setMessages([]);
      setArtifacts([]);
      setSelectedArtifactIds([]);
    }
  }, [currentSessionId])

  const loadArtifacts = async (sessionId: string) => {
    try {
      const items = await listArtifacts(sessionId);
      setArtifacts(items);
    } catch (error) {
      console.error("Failed to load artifacts", error);
    }
  }

  // Scroll to bottom on messages change or streaming
  useEffect(() => {
    scrollToBottom();
  }, [messages, isStreaming, showReasoning])

  const scrollToBottom = () => {
    if (scrollRef.current) {
        // Use timeout to ensure DOM update
        setTimeout(() => {
            if (scrollRef.current) {
                scrollRef.current.scrollIntoView({ behavior: 'smooth' });
            }
        }, 100)
    }
  }

  const refreshSessions = async () => {
    try {
      const sess = await getSessions(userId);
      setSessions(sess);
    } catch (error) {
      console.error("Failed to load sessions", error);
    }
  }

  const loadHistory = async (sessionId: string) => {
    try {
      // Always fetch with reasoning included so we can toggle visibility client-side
      const hist = await getHistory(userId, sessionId, true);
      setMessages(normalizeHistoryMessages(hist));
    } catch (error) {
      console.error("Failed to load history", error);
    }
  }

  const handleCreateSession = () => {
    setCurrentSessionId(null); // Will create new on first message
    setMessages([]);
    setIsLeftSidebarOpen(false);
  }

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm("Are you sure you want to delete this session?")) {
      await deleteSession(userId, sessionId);
      await refreshSessions();
      if (currentSessionId === sessionId) {
        setCurrentSessionId(null);
        setMessages([]);
      }
    }
  }

  const handleCopySessionId = (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(sessionId);
    // Suggest showing a toast here? For now just copy.
  }

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';

    if (!currentSessionId) {
      alert('Send a message first to create a session, then upload files.');
      return;
    }

    try {
      const artifact = await uploadArtifact(currentSessionId, file);
      setArtifacts((prev) => [artifact, ...prev]);
      setSelectedArtifactIds((prev) => [...prev, artifact.id]);
      if (file.type === 'text/csv' || file.name.endsWith('.csv')) {
        const reader = new FileReader();
        reader.onload = (ev) => {
          const content = ev.target?.result as string;
          setCsvFile({ name: file.name, content });
        };
        reader.readAsText(file);
      }
    } catch (error) {
      console.error('Upload failed', error);
      alert('Failed to upload file');
    }
  }

  const handleArtifactUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !currentSessionId) return;
    e.target.value = '';
    try {
      const artifact = await uploadArtifact(currentSessionId, file);
      setArtifacts((prev) => [artifact, ...prev]);
      setSelectedArtifactIds((prev) => [...prev, artifact.id]);
    } catch (error) {
      console.error('Artifact upload failed', error);
    }
  }

  const handleDeleteArtifact = async (artifactId: string) => {
    if (!currentSessionId) return;
    await deleteArtifact(currentSessionId, artifactId);
    setArtifacts((prev) => prev.filter((a) => a.id !== artifactId));
    setSelectedArtifactIds((prev) => prev.filter((id) => id !== artifactId));
  }

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files) {
      Array.from(files).forEach(file => {
        if (!file.type.startsWith('image/')) {
          alert('Please upload image files only');
          return;
        }
        const reader = new FileReader();
        reader.onload = (event) => {
          const base64 = event.target?.result as string;
          setImages(prev => [...prev, { name: file.name, base64 }]);
        };
        reader.readAsDataURL(file);
      });
    }
    e.target.value = '';
  }

  const removeImage = (index: number) => {
    setImages(prev => prev.filter((_, i) => i !== index));
  }

  const sendMessage = () => {
    if (!input.trim() || isStreaming) return;

    // Determine session ID (use current or leave empty to generate new)
    const payload = {
      query: input,
      user_id: userId,
      session_id: currentSessionId,
      include_reasoning: useReasoning,
      images: images.length > 0 ? images.map(img => img.base64) : null,
      csv_data: csvFile ? csvFile.content : null,
      artifact_ids: selectedArtifactIds.length > 0 ? selectedArtifactIds : null,
    };

    // Optimistic update
    const attachmentInfo = [
      csvFile ? `[CSV: ${csvFile.name}]` : '',
      images.length > 0 ? `[${images.length} image(s)]` : ''
    ].filter(Boolean).join(' ');
    
    const userMsg: MessageType = {
        role: "user",
        content: input + (attachmentInfo ? `\n\n${attachmentInfo}` : ""),
        step_kind: "user",
        timestamp: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setCsvFile(null);
    setImages([]);
    setIsStreaming(true);

    // WebSocket logic - dynamic protocol and host
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/chat/ws`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
        ws.send(JSON.stringify(payload));
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === "info" && data.session_id) {
            if (!currentSessionId) {
                setCurrentSessionId(data.session_id);
                refreshSessions();
            }
        } else if (data.type === "step") {
            appendStepMessage({
                role: "assistant",
                content: JSON.stringify(data.step),
                is_reasoning: !data.step.is_final_answer,
                step_kind: "assistant",
                timestamp: new Date().toISOString(),
            });
            if (data.step.is_final_answer) {
                setIsStreaming(false);
                ws.close();
            }
        } else if (data.type === "tool") {
            appendStepMessage({
                role: "assistant",
                content: JSON.stringify({ output: data.content }),
                is_reasoning: true,
                step_kind: "tool",
                timestamp: new Date().toISOString(),
            });
        } else if (data.type === "error") {
            appendStepMessage({
                role: "assistant",
                content: JSON.stringify({ output: data.content }),
                is_reasoning: true,
                step_kind: "tool",
                timestamp: new Date().toISOString(),
            });
            setIsStreaming(false);
            ws.close();
        }
    };

    ws.onerror = (error) => {
        console.error("WebSocket Error:", error);
        setIsStreaming(false);
    };

    ws.onclose = () => {
        setIsStreaming(false);
    };
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          sendMessage();
      }
  }

  return (
    <div className="flex h-[100dvh] w-full bg-background text-foreground overflow-hidden relative">
      {/* Mobile Overlay Backgrounds */}
      {(isLeftSidebarOpen || isRightSidebarOpen) && (
        <div 
            className="fixed inset-0 bg-black/50 z-40 md:hidden"
            onClick={() => {
                setIsLeftSidebarOpen(false);
                setIsRightSidebarOpen(false);
            }}
        />
      )}

      {/* Left Sidebar: Sessions */}
      <div className={cn(
        "fixed inset-y-0 left-0 z-50 w-64 border-r border-border bg-card flex flex-col transition-transform duration-300 ease-in-out md:relative md:translate-x-0 pb-safe h-full max-h-[100dvh] overflow-hidden",
        isLeftSidebarOpen ? "translate-x-0" : "-translate-x-full"
      )}>
        <div className="p-4 border-b border-border flex items-center justify-between">
          <h2 className="font-bold text-lg">Chats</h2>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon" onClick={handleCreateSession}>
                <Plus className="h-5 w-5" />
            </Button>
            {/* Mobile Close Button */}
            <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setIsLeftSidebarOpen(false)}>
                <X className="h-5 w-5" />
            </Button>
          </div>
        </div>
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-2">
            {sessions.length === 0 && (
                <div className="p-4 text-center text-sm text-muted-foreground">
                    No chats found.
                </div>
            )}
            {sessions.map(sid => (
              <div 
                key={sid} 
                onClick={() => setCurrentSessionId(sid)}
                className={cn(
                  "group flex items-center justify-between p-3 rounded-md cursor-pointer hover:bg-accent hover:text-accent-foreground transition-colors overflow-hidden",
                  currentSessionId === sid && "bg-accent text-accent-foreground"
                )}
              >
                <div className="flex-1 min-w-0 mr-2">
                    <p className="truncate text-sm font-medium">
                        {sid.slice(0, 8)}...{sid.slice(-4)}
                    </p>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={(e) => handleCopySessionId(sid, e)}>
                        <Copy className="h-4 w-4" />
                    </Button>
                    <Button size="icon" className="h-7 w-7 bg-red-500 hover:bg-red-600 text-white shadow-sm" onClick={(e) => {
                        handleDeleteSession(sid, e);
                    }}>
                        <Trash2 className="h-4 w-4" />
                    </Button>
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col relative min-h-0 w-full transition-all duration-300">
        
        {/* Mobile Header */}
        <div className="md:hidden h-14 border-b border-border flex items-center justify-between px-4 bg-background">
            <Button variant="ghost" size="icon" onClick={() => setIsLeftSidebarOpen(true)}>
                <Menu className="h-5 w-5" />
            </Button>
            <span className="font-semibold text-sm">RootAgent</span>
            <Button variant="ghost" size="icon" onClick={() => setIsRightSidebarOpen(true)}>
                <Settings2 className="h-5 w-5" />
            </Button>
        </div>

        <div className="flex-1 min-h-0">
            <ScrollArea className="h-full w-full p-4">
                <div className="space-y-6 max-w-4xl mx-auto pb-20"> {/* pb-20 for input area space */}
                    {messages.map((msg, idx) => {
                        if (shouldHideMessage(msg, showReasoning)) return null;
                        return (
                            <ChatMessageBubble
                                key={msg.message_id ?? idx}
                                msg={msg}
                                theme={theme}
                            />
                        );
                    })}

                    {isStreaming && (
                        <div className="flex items-center gap-2 text-sm text-muted-foreground px-2">
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Agent is working...
                        </div>
                    )}
                    <div ref={scrollRef} />
                </div>
            </ScrollArea>
        </div>

        {/* Input Area */}
        <div className="p-4 border-t border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
            <div className="max-w-4xl mx-auto flex flex-col gap-2">
                {csvFile && (
                    <div className="flex items-center gap-2 bg-muted p-2 rounded-md w-fit text-sm animate-in fade-in slide-in-from-bottom-2">
                        <span className="font-medium text-xs flex items-center gap-1">
                            <Paperclip className="h-3 w-3" />
                            {csvFile.name}
                        </span>
                        <Button 
                            variant="ghost" 
                            size="icon" 
                            className="h-4 w-4 hover:bg-destructive/10 hover:text-destructive"
                            onClick={() => setCsvFile(null)}
                        >
                            <X className="h-3 w-3" />
                        </Button>
                    </div>
                )}
                {images.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                        {images.map((img, idx) => (
                            <div key={idx} className="relative group">
                                <img 
                                    src={img.base64} 
                                    alt={img.name} 
                                    className="h-16 w-16 object-cover rounded-md border border-border"
                                />
                                <Button 
                                    variant="destructive" 
                                    size="icon" 
                                    className="h-4 w-4 absolute -top-1 -right-1 opacity-0 group-hover:opacity-100 transition-opacity"
                                    onClick={() => removeImage(idx)}
                                >
                                    <X className="h-3 w-3" />
                                </Button>
                            </div>
                        ))}
                    </div>
                )}
                <div className="flex items-end gap-2 w-full">
                    <input 
                        type="file" 
                        ref={fileInputRef} 
                        className="hidden" 
                        accept="*/*"
                        onChange={handleFileSelect}
                    />
                    <input 
                        type="file" 
                        ref={imageInputRef} 
                        className="hidden" 
                        accept="image/*"
                        multiple
                        onChange={handleImageSelect}
                    />
                    <Button 
                        variant="outline" 
                        size="icon"
                        className="h-[60px] w-[60px] shrink-0"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={isStreaming}
                        title="Upload CSV"
                    >
                        <Paperclip className="h-5 w-5" />
                    </Button>
                    <Button 
                        variant="outline" 
                        size="icon"
                        className="h-[60px] w-[60px] shrink-0"
                        onClick={() => imageInputRef.current?.click()}
                        disabled={isStreaming}
                        title="Upload Images"
                    >
                        <ImagePlus className="h-5 w-5" />
                    </Button>
                    <Textarea 
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder="Type a message..."
                        className="min-h-[60px] resize-none"
                        disabled={isStreaming}
                    />
                    <Button onClick={sendMessage} disabled={(!input.trim() && !csvFile && images.length === 0) || isStreaming} className="h-[60px] w-[60px] shrink-0">
                        {isStreaming ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
                    </Button>
                </div>
            </div>
        </div>
      </div>

      {/* Right Sidebar: Settings */}
      <div className={cn(
        "fixed inset-y-0 right-0 z-50 w-72 border-l border-border bg-card p-6 flex flex-col space-y-6 transition-transform duration-300 ease-in-out lg:relative lg:translate-x-0 pb-safe h-full max-h-[100dvh] overflow-hidden",
        isRightSidebarOpen ? "translate-x-0" : "translate-x-full"
      )}>
        <div className="flex items-center justify-between lg:hidden mb-4">
            <span className="font-bold">Settings</span>
            <Button variant="ghost" size="icon" onClick={() => setIsRightSidebarOpen(false)}>
                <X className="h-5 w-5" />
            </Button>
        </div>
        
        <div>
            <h2 className="font-bold text-lg mb-4 hidden lg:block">Control Panel</h2>
            <div className="space-y-6">
                <div className="space-y-2">
                    <h3 className="text-sm font-medium leading-none">Reasoning</h3>
                    <p className="text-xs text-muted-foreground">Manage how the AI thinks.</p>
                </div>
                
                <div className="flex items-center justify-between space-x-2">
                    <Label htmlFor="use-reasoning" className="flex flex-col space-y-1">
                        <span>Use Reasoning</span>
                        <span className="font-normal text-xs text-muted-foreground">Enable Chain-of-Thought</span>
                    </Label>
                    <Switch 
                        id="use-reasoning" 
                        checked={useReasoning} 
                        onCheckedChange={setUseReasoning} 
                    />
                </div>
                
                <div className="flex items-center justify-between space-x-2">
                    <Label htmlFor="show-reasoning" className="flex flex-col space-y-1">
                        <span>Show Reasoning</span>
                        <span className="font-normal text-xs text-muted-foreground">Display thinking process</span>
                    </Label>
                    <Switch 
                        id="show-reasoning" 
                        checked={showReasoning} 
                        onCheckedChange={setShowReasoning} 
                    />
                </div>

                <div className="space-y-4">
                     <h3 className="text-sm font-medium leading-none">Appearance</h3>
                     <div className="flex items-center justify-between space-x-2">
                         <Label className="flex flex-col space-y-1">
                             <span>Theme</span>
                             <span className="font-normal text-xs text-muted-foreground">Toggle Dark/Light mode</span>
                         </Label>
                         <Button variant="ghost" size="icon" onClick={() => setTheme(prev => prev === 'dark' ? 'light' : 'dark')}>
                             {theme === 'dark' ? <Moon className="h-5 w-5" /> : <Sun className="h-5 w-5" />}
                         </Button>
                     </div>
                </div>

                <div className="space-y-4">
                     <h3 className="text-sm font-medium leading-none">Account</h3>
                     <div className="text-xs text-muted-foreground">
                        Logged in as <span className="font-bold text-foreground">{user?.email}</span>
                     </div>
                     <Button variant="outline" size="sm" className="w-full text-destructive hover:bg-destructive/10" onClick={logout}>
                        Logout
                     </Button>
                </div>

                <Separator />

                <div className="space-y-2">
                  <h3 className="text-sm font-medium leading-none">Artifacts</h3>
                  <p className="text-xs text-muted-foreground">
                    Files for this chat (upload, preview, download, delete).
                  </p>
                  <input
                    type="file"
                    className="hidden"
                    id="artifact-upload"
                    onChange={handleArtifactUpload}
                    disabled={!currentSessionId || isStreaming}
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full"
                    disabled={!currentSessionId}
                    onClick={() =>
                      document.getElementById('artifact-upload')?.click()
                    }
                  >
                    Upload file
                  </Button>
                  <ScrollArea className="h-40 rounded border border-border p-2">
                    {artifacts.length === 0 ? (
                      <p className="text-xs text-muted-foreground">No artifacts yet.</p>
                    ) : (
                      <ul className="space-y-2">
                        {artifacts.map((a) => (
                          <li
                            key={a.id}
                            className="text-xs border border-border rounded p-2 space-y-1"
                          >
                            <div className="font-medium truncate">{a.filename}</div>
                            <div className="flex flex-wrap gap-1">
                              {a.preview_url && (
                                <a
                                  href={a.preview_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="underline text-primary"
                                >
                                  Preview
                                </a>
                              )}
                              <a
                                href={getArtifactDownloadUrl(
                                  currentSessionId!,
                                  a.id
                                )}
                                className="underline text-primary"
                              >
                                Download
                              </a>
                              <button
                                type="button"
                                className="text-destructive underline"
                                onClick={() => handleDeleteArtifact(a.id)}
                              >
                                Delete
                              </button>
                            </div>
                            <label className="flex items-center gap-1">
                              <input
                                type="checkbox"
                                checked={selectedArtifactIds.includes(a.id)}
                                onChange={(e) => {
                                  if (e.target.checked) {
                                    setSelectedArtifactIds((prev) => [
                                      ...prev,
                                      a.id,
                                    ]);
                                  } else {
                                    setSelectedArtifactIds((prev) =>
                                      prev.filter((id) => id !== a.id)
                                    );
                                  }
                                }}
                              />
                              Include in prompt
                            </label>
                          </li>
                        ))}
                      </ul>
                    )}
                  </ScrollArea>
                </div>

                <Separator />

                {currentSessionId && (
                     <div className="space-y-2">
                        <h3 className="text-sm font-medium leading-none">Current Session</h3>
                        <div className="p-2 bg-muted rounded text-xs font-mono break-all relative group">
                            {currentSessionId}
                            <Button 
                                variant="secondary" 
                                size="icon" 
                                className="h-5 w-5 absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity"
                                onClick={(e) => handleCopySessionId(currentSessionId, e)}
                            >
                                <Copy className="h-3 w-3" />
                            </Button>
                        </div>
                     </div>
                )}
            </div>
        </div>
      </div>
    </div>
  )
}
