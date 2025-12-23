import { useState, useEffect, useRef } from 'react'
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { Card } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Textarea } from "@/components/ui/textarea"
import { Separator } from "@/components/ui/separator"
import type { Message as MessageType } from "@/types"
import { getSessions, deleteSession, getHistory } from "@/api"
import { Trash2, Copy, Send, Plus, Loader2 } from "lucide-react"
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from "@/lib/utils"

import { useAuth } from "@/lib/auth-context";

export default function Chat() {
  const { user, logout } = useAuth();
  const userId = user?.user_id || "anonymous";
  const [sessions, setSessions] = useState<string[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<MessageType[]>([])
  const [input, setInput] = useState("")
  const [useReasoning, setUseReasoning] = useState(true)
  const [showReasoning, setShowReasoning] = useState(true)
  const [streamingContent, setStreamingContent] = useState("")
  const [isStreaming, setIsStreaming] = useState(false)
  
  const scrollRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)

  const streamingContentRef = useRef("")

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
    } else {
      setMessages([]);
    }
  }, [currentSessionId])

  // Scroll to bottom on messages change or streaming
  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingContent, showReasoning])

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
      setMessages(hist);
    } catch (error) {
      console.error("Failed to load history", error);
    }
  }

  const handleCreateSession = () => {
    setCurrentSessionId(null); // Will create new on first message
    setMessages([]);
    setStreamingContent("");
    streamingContentRef.current = "";
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

  const sendMessage = () => {
    if (!input.trim() || isStreaming) return;

    // Determine session ID (use current or leave empty to generate new)
    const payload = {
      query: input,
      user_id: userId,
      session_id: currentSessionId,
      include_reasoning: useReasoning,
      images: null, // Image support can be added later
      csv_data: null
    };

    // Optimistic update
    const userMsg: MessageType = {
        role: "user",
        content: input,
        timestamp: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setIsStreaming(true);
    streamingContentRef.current = "";

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
        } else if (data.type === "token") {
            streamingContentRef.current += data.content;
            setStreamingContent(prev => prev + data.content);
        } else if (data.type === "step_separator") {
            // End of a reasoning step
            setMessages(prev => [
                ...prev,
                {
                    role: "assistant",
                    content: streamingContentRef.current, // The accumulated content is reasoning
                    is_reasoning: true, // Mark as reasoning
                    timestamp: new Date().toISOString()
                }
            ]);
            setStreamingContent(""); // Reset
            streamingContentRef.current = "";
        } else if (data.type === "observation" || data.type === "error") {
            setMessages(prev => {
                const newMessages = [...prev]
                // Commit any pending reasoning
                if (streamingContentRef.current) {
                    newMessages.push({
                         role: "assistant",
                         content: streamingContentRef.current,
                         is_reasoning: true,
                         timestamp: new Date().toISOString()
                    })
                }
                // Add the observation
                newMessages.push({
                    role: "assistant", // Using assistant role for rendering, but with is_reasoning=true
                    content: data.content,
                    is_reasoning: true,
                    timestamp: new Date().toISOString()
                })
                return newMessages
            });
            setStreamingContent("");
            streamingContentRef.current = "";
        } else if (data.type === "final") {
             // Save any remaining streaming content as reasoning
             setMessages(prev => {
                const newMessages = [...prev]
                if (streamingContentRef.current) {
                     newMessages.push({
                        role: "assistant",
                        content: streamingContentRef.current,
                        is_reasoning: true,
                        timestamp: new Date().toISOString()
                    })
                }
                newMessages.push({
                    role: "assistant",
                    content: data.content,
                    is_reasoning: false,
                    timestamp: new Date().toISOString()
                })
                return newMessages
             });
             setIsStreaming(false);
             setStreamingContent("");
             streamingContentRef.current = "";
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
    <div className="flex h-screen w-full bg-background text-foreground overflow-hidden">
      {/* Left Sidebar: Sessions */}
      <div className="w-64 border-r border-border bg-card flex flex-col">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <h2 className="font-bold text-lg">Chats</h2>
          <Button variant="ghost" size="icon" onClick={handleCreateSession}>
            <Plus className="h-5 w-5" />
          </Button>
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
      <div className="flex-1 flex flex-col relative min-h-0">
        <div className="flex-1 min-h-0">
            <ScrollArea className="h-full w-full p-4">
                <div className="space-y-6 max-w-4xl mx-auto pb-20"> {/* pb-20 for input area space */}
                    {messages.map((msg, idx) => {
                        // Logic to hide reasoning/observations if showReasoning is false
                        if (msg.is_reasoning && !showReasoning) return null;

                        // Parse content if it's a JSON string (for backend stored user messages)
                        let displayContent = msg.content;
                        try {
                            if (msg.role === 'user' && typeof msg.content === 'string' && (msg.content.startsWith('{') || msg.content.startsWith('['))) {
                                const parsed = JSON.parse(msg.content);
                                if (Array.isArray(parsed)) {
                                    displayContent = parsed.map((p: any) => p.text || '').join('');
                                } else if (parsed.text) {
                                    displayContent = parsed.text;
                                }
                            }
                        } catch (e) {
                            // Keep original content if parsing fails
                        }

                        // Pre-process content to fix markdown rendering issues
                        // Ensure code blocks start on a new line
                        if (typeof displayContent === 'string') {
                             displayContent = displayContent.replace(/([^\n])```/g, '$1\n```');
                        }

                        const isObservation = msg.role === "user" && msg.is_reasoning;
                        const isThinking = msg.role === "assistant" && msg.is_reasoning;

                        return (
                            <div key={idx} className={cn(
                                "flex flex-col space-y-2",
                                msg.role === "user" ? "items-end" : "items-start"
                            )}>
                                <Card className={cn(
                                    "p-4 max-w-[85%] shadow-sm",
                                    !msg.is_reasoning && msg.role === "user" && "bg-primary text-primary-foreground",
                                    !msg.is_reasoning && msg.role !== "user" && "bg-secondary",
                                    isThinking && "border-l-4 border-yellow-500 bg-muted/50 text-muted-foreground w-full max-w-full", // Reasoning styling
                                    isObservation && "border-l-4 border-blue-500 bg-blue-50/50 dark:bg-blue-950/20 text-muted-foreground w-full max-w-full" // Observation styling
                                )}>
                                    {isThinking && <div className="text-xs font-mono uppercase mb-2 text-yellow-500 flex items-center gap-2">Thinking...</div>}
                                    {isObservation && <div className="text-xs font-mono uppercase mb-2 text-blue-500 flex items-center gap-2">System Observation</div>}
                                    <div className="prose prose-invert max-w-none text-sm leading-relaxed break-words">
                                    <ReactMarkdown 
                                        remarkPlugins={[remarkGfm]}
                                        components={{
                                            code({node, className, children, ...props}) {
                                                const match = /language-(\w+)/.exec(className || '')
                                                return match ? (
                                                <div className="rounded-md bg-black/50 p-2 my-2 overflow-x-auto">
                                                    <code className={className} {...props}>{children}</code>
                                                </div>
                                                ) : (
                                                <code className="bg-black/20 rounded px-1" {...props}>{children}</code>
                                                )
                                            }
                                        }}
                                    >
                                        {displayContent}
                                    </ReactMarkdown>
                                    </div>
                                </Card>
                            </div>
                        )
                    })}
                    
                    {/* Streaming Indicator / Content */}
                    {isStreaming && streamingContent && (
                        <div className="flex flex-col space-y-2 items-start opacity-80">
                            <Card className={cn(
                                "p-4 w-full shadow-sm bg-muted/50 text-muted-foreground border-l-4 border-yellow-500",
                                !showReasoning && "hidden" // Hide streaming reasoning if toggled off
                            )}>
                                <div className="text-xs font-mono uppercase mb-2 text-yellow-500 flex items-center gap-2">
                                     <Loader2 className="h-3 w-3 animate-spin" /> Thinking...
                                </div>
                                <div className="prose prose-invert max-w-none text-sm">
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingContent}</ReactMarkdown>
                                </div>
                            </Card>
                        </div>
                    )}
                    <div ref={scrollRef} />
                </div>
            </ScrollArea>
        </div>

        {/* Input Area */}
        <div className="p-4 border-t border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
            <div className="max-w-4xl mx-auto flex items-end gap-2">
                <Textarea 
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Type a message..."
                    className="min-h-[60px] resize-none"
                    disabled={isStreaming}
                />
                <Button onClick={sendMessage} disabled={!input.trim() || isStreaming} className="h-[60px] w-[60px]">
                    {isStreaming ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
                </Button>
            </div>
        </div>
      </div>

      {/* Right Sidebar: Settings */}
      <div className="w-72 border-l border-border bg-card p-6 flex flex-col space-y-6">
        <div>
            <h2 className="font-bold text-lg mb-4">Control Panel</h2>
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
                     <h3 className="text-sm font-medium leading-none">Account</h3>
                     <div className="text-xs text-muted-foreground">
                        Logged in as <span className="font-bold text-foreground">{user?.username}</span>
                     </div>
                     <Button variant="outline" size="sm" className="w-full text-destructive hover:bg-destructive/10" onClick={logout}>
                        Logout
                     </Button>
                </div>

                <Separator />

                <div className="space-y-4">
                     <h3 className="text-sm font-medium leading-none">Customization Tokens</h3>
                     {/* Placeholder for future customization tokens */}
                     <div className="grid gap-2">
                        <Label htmlFor="max-tokens" className="text-xs">Max Tokens (Example)</Label>
                        <Textarea id="custom-tokens" placeholder="Enter custom system tokens or context..." className="h-24 text-xs font-mono" />
                     </div>
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
