"""
History Manager Module
Manages conversation history with automatic summarization when history exceeds 6 rounds.
"""

import json
from typing import List, Dict, Any, Tuple
from datetime import datetime


class HistoryManager:
    """
    Manages installation conversation history with intelligent summarization.
    
    When history reaches 6+ rounds, it automatically summarizes the first 4 rounds
    and keeps only the latest 2 rounds plus the summary.
    """
    
    def __init__(self, summarizer=None):
        """
        Initialize history manager.
        
        Args:
            summarizer: AI model instance for history summarization
        """
        self.history: List[Dict[str, Any]] = []
        self.summary: str = ""
        self.summarizer = summarizer
        self.max_history_rounds = 6
        self.keep_recent_rounds = 2
        
    def add_entry(self, entry_type: str, content: str, metadata: Dict = None):
        """
        Add a new entry to history.
        
        Args:
            entry_type: Type of entry (user_request, search_query, search_result, 
                       installation_plan, execution_result, error, completion)
            content: The actual content
            metadata: Additional metadata (step number, timestamp, etc.)
        """
        entry = {
            "type": entry_type,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        
        self.history.append(entry)
        
        # Check if we need to summarize
        if len(self.history) >= self.max_history_rounds:
            self._summarize_history()
    
    def _summarize_history(self):
        """
        Summarize history when it exceeds the maximum rounds.
        Keeps summary + recent rounds.
        """
        if not self.summarizer:
            # If no summarizer available, just keep recent entries
            self.history = self.history[-self.keep_recent_rounds:]
            return
        
        # Get entries to summarize (first 4 rounds)
        entries_to_summarize = self.history[:-self.keep_recent_rounds]
        recent_entries = self.history[-self.keep_recent_rounds:]
        
        # Create summarization prompt
        history_text = self._format_history_for_summary(entries_to_summarize)
        
        summary_prompt = f"""
请总结以下软件安装过程的历史记录，保留关键信息：

之前的总结：
{self.summary}

需要总结的历史记录：
{history_text}

请提供一个简洁但完整的总结，包括：
1. 用户的安装需求
2. 已完成的主要步骤
3. 遇到的问题和解决方案
4. 当前的安装状态

总结应该简洁明了，为后续的安装步骤提供必要的上下文。
"""
        
        try:
            # Get summary from AI model
            new_summary = self.summarizer.chat(summary_prompt)
            if isinstance(new_summary, tuple):
                new_summary = new_summary[0]  # Handle Deepseek return format
            
            self.summary = new_summary
            self.history = recent_entries
            
        except Exception as e:
            print(f"History summarization failed: {e}")
            # Fallback: just keep recent entries
            self.history = recent_entries
    
    def _format_history_for_summary(self, entries: List[Dict]) -> str:
        """Format history entries for summarization."""
        formatted = []
        for i, entry in enumerate(entries, 1):
            formatted.append(f"步骤 {i} ({entry['type']}):")
            formatted.append(f"内容: {entry['content']}")
            if entry.get('metadata'):
                formatted.append(f"元数据: {entry['metadata']}")
            formatted.append("")
        
        return "\n".join(formatted)
    
    def get_context_for_ai(self) -> str:
        """
        Get formatted history context for AI models.
        
        Returns:
            Formatted string containing summary and recent history
        """
        context_parts = []
        
        if self.summary:
            context_parts.append("=== 历史总结 ===")
            context_parts.append(self.summary)
            context_parts.append("")
        
        if self.history:
            context_parts.append("=== 最近的操作历史 ===")
            for i, entry in enumerate(self.history, 1):
                context_parts.append(f"步骤 {i} ({entry['type']}):")
                context_parts.append(f"时间: {entry['timestamp']}")
                context_parts.append(f"内容: {entry['content']}")
                if entry.get('metadata'):
                    context_parts.append(f"元数据: {entry['metadata']}")
                context_parts.append("")
        
        return "\n".join(context_parts)
    
    def get_full_history(self) -> Dict[str, Any]:
        """
        Get complete history including summary.
        
        Returns:
            Dictionary containing summary and current history
        """
        return {
            "summary": self.summary,
            "current_history": self.history,
            "total_entries": len(self.history)
        }
    
    def save_to_file(self, filepath: str):
        """Save history to JSON file."""
        history_data = {
            "summary": self.summary,
            "history": self.history,
            "saved_at": datetime.now().isoformat()
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)
    
    def load_from_file(self, filepath: str):
        """Load history from JSON file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
            
            self.summary = history_data.get("summary", "")
            self.history = history_data.get("history", [])
            
        except FileNotFoundError:
            print(f"History file {filepath} not found, starting with empty history")
        except Exception as e:
            print(f"Error loading history: {e}")
    
    def clear_history(self):
        """Clear all history and summary."""
        self.history = []
        self.summary = ""
    
    def get_step_count(self) -> int:
        """Get total number of steps in current session."""
        return len(self.history)