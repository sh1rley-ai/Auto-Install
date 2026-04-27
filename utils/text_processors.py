"""
Text Processing Utilities
Provides text extraction and processing functions for the installation system.
"""

import re
from typing import List, Optional, Dict, Any


class TextProcessor:
    """
    Utility class for processing text content from AI responses.
    
    Handles extraction of queries, code blocks, and other structured content
    from AI model responses.
    """
    
    @staticmethod
    def extract_search_queries(text: str) -> List[str]:
        """
        Extract search queries from text using multiple patterns.
        
        Args:
            text: Input text containing search queries
            
        Returns:
            List of extracted search queries
        """
        patterns = [
            r'<搜索词>(.*?)</搜索词>',
            r'<query>(.*?)</query>',
            r'<search>(.*?)</search>'
        ]
        
        queries = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            queries.extend([match.strip() for match in matches])
        
        return queries
    
    @staticmethod
    def extract_python_code(text: str) -> Optional[str]:
        """
        Extract Python code from markdown code blocks.
        
        Args:
            text: Input text containing Python code blocks
            
        Returns:
            Extracted Python code or None if not found
        """
        pattern = r'```python\s+(.*?)```'
        match = re.search(pattern, text, re.DOTALL)
        
        if match:
            return match.group(1).strip()
        
        # Try alternative patterns
        alt_patterns = [
            r'```py\s+(.*?)```',
            r'```\s*python\s+(.*?)```'
        ]
        
        for pattern in alt_patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()
        
        return None
    
    @staticmethod
    def extract_shell_commands(text: str) -> List[str]:
        """
        Extract shell commands from text.
        
        Args:
            text: Input text containing shell commands
            
        Returns:
            List of extracted shell commands
        """
        patterns = [
            r'```bash\s+(.*?)```',
            r'```sh\s+(.*?)```',
            r'```shell\s+(.*?)```',
            r'```\s*\$\s+(.*?)```'
        ]
        
        commands = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            commands.extend([match.strip() for match in matches])
        
        return commands
    
    @staticmethod
    def extract_installation_plan(text: str) -> Optional[str]:
        """
        Extract installation plan from text.
        
        Args:
            text: Input text containing installation plan
            
        Returns:
            Extracted installation plan or None if not found
        """
        patterns = [
            r'<计划>(.*?)</计划>',
            r'<plan>(.*?)</plan>',
            r'<installation_plan>(.*?)</installation_plan>'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()
        
        return None
    
    @staticmethod
    def check_completion_markers(text: str) -> bool:
        """
        Check if text contains completion markers.
        
        Args:
            text: Input text to check
            
        Returns:
            True if completion markers found, False otherwise
        """
        completion_markers = [
            '<安装完成>',
            '<installation_complete>',
            '<完成>',
            '<complete>',
            '<done>'
        ]
        
        text_lower = text.lower()
        return any(marker.lower() in text_lower for marker in completion_markers)
    
    @staticmethod
    def extract_error_messages(text: str) -> List[str]:
        """
        Extract error messages from text.
        
        Args:
            text: Input text containing error messages
            
        Returns:
            List of extracted error messages
        """
        patterns = [
            r'error:\s*(.*?)(?:\n|$)',
            r'错误:\s*(.*?)(?:\n|$)',
            r'exception:\s*(.*?)(?:\n|$)',
            r'异常:\s*(.*?)(?:\n|$)'
        ]
        
        errors = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
            errors.extend([match.strip() for match in matches])
        
        return errors
    
    @staticmethod
    def clean_code_output(output: str, max_length: int = 1000) -> str:
        """
        Clean and truncate code execution output.
        
        Args:
            output: Raw output from code execution
            max_length: Maximum length to keep
            
        Returns:
            Cleaned and truncated output
        """
        if not output:
            return ""
        
        # Remove excessive whitespace
        cleaned = re.sub(r'\n\s*\n\s*\n', '\n\n', output)
        cleaned = cleaned.strip()
        
        # Truncate if too long
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length] + f"\n... (输出被截断，原长度: {len(output)} 字符)"
        
        return cleaned
    
    @staticmethod
    def extract_structured_content(text: str) -> Dict[str, Any]:
        """
        Extract all structured content from text in one pass.
        
        Args:
            text: Input text to process
            
        Returns:
            Dictionary containing all extracted content
        """
        return {
            'search_queries': TextProcessor.extract_search_queries(text),
            'python_code': TextProcessor.extract_python_code(text),
            'shell_commands': TextProcessor.extract_shell_commands(text),
            'installation_plan': TextProcessor.extract_installation_plan(text),
            'is_complete': TextProcessor.check_completion_markers(text),
            'error_messages': TextProcessor.extract_error_messages(text)
        }
    
    @staticmethod
    def format_for_display(text: str, max_width: int = 80) -> str:
        """
        Format text for console display with proper wrapping.
        
        Args:
            text: Text to format
            max_width: Maximum line width
            
        Returns:
            Formatted text
        """
        if not text:
            return ""
        
        lines = text.split('\n')
        formatted_lines = []
        
        for line in lines:
            if len(line) <= max_width:
                formatted_lines.append(line)
            else:
                # Simple word wrapping
                words = line.split(' ')
                current_line = ""
                
                for word in words:
                    if len(current_line + word) <= max_width:
                        current_line += word + " "
                    else:
                        if current_line:
                            formatted_lines.append(current_line.rstrip())
                        current_line = word + " "
                
                if current_line:
                    formatted_lines.append(current_line.rstrip())
        
        return '\n'.join(formatted_lines)
    
    @staticmethod
    def extract_version_info(text: str) -> Dict[str, str]:
        """
        Extract version information from text.
        
        Args:
            text: Input text containing version info
            
        Returns:
            Dictionary with extracted version information
        """
        version_patterns = {
            'version': r'version\s*:?\s*([0-9]+(?:\.[0-9]+)*)',
            'v': r'v([0-9]+(?:\.[0-9]+)*)',
            '版本': r'版本\s*:?\s*([0-9]+(?:\.[0-9]+)*)'
        }
        
        versions = {}
        text_lower = text.lower()
        
        for key, pattern in version_patterns.items():
            matches = re.findall(pattern, text_lower)
            if matches:
                versions[key] = matches[0]
        
        return versions