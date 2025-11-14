#!/usr/bin/env python3
"""
Google Drive MCP Server for Gemini CLI
Enables access to Google Drive documents (.gdoc, .gsheet, .gslides) via the Windows virtual drive.
"""

import asyncio
import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
)


# Google Drive API scopes
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/documents.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/presentations.readonly',
]

# Configure logging
# Log to both stderr (for CLI visibility) and a log file
LOG_LEVEL = os.getenv('MCP_LOG_LEVEL', 'DEBUG').upper()
LOG_FILE = os.getenv('MCP_LOG_FILE', 'mcp_server.log')

# Create logger
logger = logging.getLogger('google_drive_mcp')
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# Clear any existing handlers
logger.handlers.clear()

# Create formatter
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Handler for stderr (may be visible in some CLI configurations)
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
stderr_handler.setFormatter(formatter)
logger.addHandler(stderr_handler)

# Handler for log file (always accessible)
try:
    file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
    file_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
except Exception as e:
    # If we can't create the log file, at least log to stderr
    logger.warning(f"Could not create log file {LOG_FILE}: {e}")

# Initialize the MCP server
app = Server("google-drive-mcp-server")


class GoogleDriveClient:
    """Client for interacting with Google Drive API."""
    
    def __init__(self, credentials_json: Optional[str] = None):
        """
        Initialize Google Drive client using OAuth2.
        
        Supports multiple authentication methods (in order of preference):
        1. GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables
        2. GOOGLE_CREDENTIALS environment variable (JSON string or file path)
        3. credentials_json parameter (JSON string or file path)
        
        Args:
            credentials_json: Optional JSON string or file path containing OAuth2 credentials.
                             If None, will try environment variables.
        """
        logger.info("Initializing Google Drive client...")
        
        # Try to get OAuth client credentials from environment variables first
        client_id = os.getenv('GOOGLE_CLIENT_ID')
        client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        
        if client_id and client_secret:
            logger.info("Using OAuth credentials from GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET")
            creds_data = {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "redirect_uris": ["http://localhost"]
                }
            }
        else:
            # Fall back to credentials_json or GOOGLE_CREDENTIALS env var
            if credentials_json is None:
                credentials_json = os.getenv('GOOGLE_CREDENTIALS')
            
            if not credentials_json:
                error_msg = (
                    "Google OAuth credentials not provided. "
                    "Set either:\n"
                    "  - GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables, or\n"
                    "  - GOOGLE_CREDENTIALS environment variable with OAuth2 credentials JSON or file path."
                )
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            try:
                creds_data = json.loads(credentials_json)
                logger.debug("Loaded credentials from JSON string")
            except json.JSONDecodeError:
                # If it's a file path, read it
                if os.path.exists(credentials_json):
                    logger.info(f"Loading credentials from file: {credentials_json}")
                    with open(credentials_json, 'r') as f:
                        creds_data = json.load(f)
                else:
                    error_msg = f"Invalid credentials: {credentials_json}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
        
        logger.info("Authenticating with Google using OAuth2...")
        self.creds = self._authenticate(creds_data)
        logger.info("Building Google API services...")
        self.drive_service = build('drive', 'v3', credentials=self.creds)
        self.docs_service = build('docs', 'v1', credentials=self.creds)
        self.sheets_service = build('sheets', 'v4', credentials=self.creds)
        self.slides_service = build('slides', 'v1', credentials=self.creds)
        logger.info("Google Drive client initialized successfully")
    
    def _authenticate(self, creds_data: Dict[str, Any]) -> Credentials:
        """
        Authenticate with Google using OAuth2 flow.
        
        Args:
            creds_data: OAuth2 client configuration (must contain 'installed' or 'web' key)
        
        Returns:
            Valid OAuth2 credentials
        """
        creds = None
        
        # Try to load existing token
        token_path = os.getenv('GOOGLE_TOKEN_PATH', 'token.json')
        if os.path.exists(token_path):
            logger.info(f"Loading existing token from {token_path}")
            try:
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            except Exception as e:
                logger.warning(f"Failed to load existing token: {e}, will re-authenticate")
                creds = None
        
        # If no valid credentials, run OAuth flow
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Token expired, refreshing...")
                try:
                    creds.refresh(Request())
                    logger.info("Token refreshed successfully")
                except Exception as e:
                    logger.warning(f"Failed to refresh token: {e}, will re-authenticate")
                    creds = None
            
            if not creds or not creds.valid:
                # Run OAuth2 flow
                if 'installed' in creds_data or 'web' in creds_data:
                    logger.info("Starting OAuth2 flow (browser will open)...")
                    logger.info("Please complete the authentication in your browser.")
                    flow = InstalledAppFlow.from_client_config(creds_data, SCOPES)
                    creds = flow.run_local_server(port=0)
                    logger.info("OAuth2 authentication completed successfully")
                else:
                    error_msg = (
                        "Invalid OAuth2 credentials format. "
                        "Credentials must contain 'installed' or 'web' key with client_id and client_secret."
                    )
                    logger.error(error_msg)
                    raise ValueError(error_msg)
            
            # Save token for future use
            if token_path and creds:
                try:
                    logger.info(f"Saving token to {token_path}")
                    with open(token_path, 'w') as token:
                        token.write(creds.to_json())
                except Exception as e:
                    logger.warning(f"Failed to save token: {e}")
        else:
            logger.info("Using existing valid token")
        
        return creds
    
    def _get_mime_type_from_extension(self, extension: str) -> str:
        """Get Google Drive MIME type from file extension."""
        mime_types = {
            '.gdoc': 'application/vnd.google-apps.document',
            '.gsheet': 'application/vnd.google-apps.spreadsheet',
            '.gslides': 'application/vnd.google-apps.presentation',
        }
        return mime_types.get(extension.lower(), '')
    
    def _parse_file_path(self, file_path: str) -> Tuple[str, str, str]:
        """
        Parse file path to extract document name, folder path, and extension.
        
        The path structure is: [drive_letter]:\[root_label]\[actual_folder_path]\[document]
        Where root_label can be "My Drive", "Shared drives", "Computers", etc.
        Only the actual_folder_path maps to Google Drive folder structure.
        
        Returns:
            (document_name, folder_path, extension)
        """
        path = Path(file_path)
        document_name = path.stem  # Name without extension
        extension = path.suffix  # .gdoc, .gsheet, .gslides
        folder_path = str(path.parent)  # Full folder path
        
        # Normalize path separators
        folder_path_normalized = folder_path.replace('\\', '/')
        
        # Handle relative paths (e.g., just "Document.gdoc" or "./Document.gdoc")
        if folder_path_normalized in ['.', './', '']:
            return document_name, '', extension
        
        # Remove drive letter (e.g., "u:/My Drive/Projects" -> "My Drive/Projects")
        if ':/' in folder_path_normalized:
            parts = folder_path_normalized.split(':/', 1)
            if len(parts) > 1:
                folder_path_normalized = parts[1]
        
        # Remove leading/trailing slashes
        folder_path_normalized = folder_path_normalized.strip('/')
        
        if not folder_path_normalized:
            return document_name, '', extension
        
        # Split into parts
        path_parts = [p.strip() for p in folder_path_normalized.split('/') if p.strip()]
        
        if not path_parts:
            return document_name, '', extension
        
        # The remaining parts are the actual folder path in Google Drive
        actual_folder_path = '/'.join(path_parts)
        
        logger.debug(f"Parsed path - Document: '{document_name}', Folder: '{actual_folder_path}'")
        
        return document_name, actual_folder_path, extension
    
    def _get_file_path(self, file_id: str) -> str:
        """
        Get the full folder path of a file by traversing its parent chain.
        
        Args:
            file_id: ID of the file
        
        Returns:
            Full folder path as a string like "Projects/Aideia/code" (actual folder names only)
        """
        path_parts = []
        current_id = file_id
        
        try:
            # First, get the file to find its parent folder
            file_info = self.drive_service.files().get(
                fileId=file_id,
                fields="id, name, parents"
            ).execute()
            
            parents = file_info.get('parents', [])
            if not parents:
                # File is in root
                return ''
            
            # Start from the file's parent folder
            current_id = parents[0]  # Usually one parent
            
            # Traverse up the parent chain to root
            while current_id and current_id != 'root':
                folder_info = self.drive_service.files().get(
                    fileId=current_id,
                    fields="id, name, parents"
                ).execute()
                
                folder_name = folder_info.get('name', '')
                parents = folder_info.get('parents', [])
                
                # If no parents or parent is 'root', we've reached a root
                if not parents or (parents and parents[0] == 'root'):
                    # Add the root folder name if it exists
                    if folder_name:
                        path_parts.insert(0, folder_name)
                    break
                
                # Add folder name to path
                if folder_name:
                    path_parts.insert(0, folder_name)
                
                current_id = parents[0]  # Move to parent
            
            final_path = '/'.join(path_parts)
            logger.debug(f"Final constructed path: '{final_path}'")
            return final_path
            
        except HttpError as e:
            logger.debug(f"Error getting path for file {file_id}: {e}")
            return ''
    
    def _normalize_path(self, path: str) -> str:
        """
        Normalize a path for comparison (remove empty parts, trim).
        
        Args:
            path: Path string like "Projects/Aideia/code"
        
        Returns:
            Normalized path
        """
        if not path:
            return ''
        parts = [p.strip() for p in path.split('/') if p.strip()]
        return '/'.join(parts)
    
    def _paths_match_backwards(self, expected_path: str, actual_path: str) -> bool:
        """
        Verify paths by matching backwards from the end.
        
        Compares the expected path (from filesystem) with the actual path (from Google Drive)
        by matching folder names from the end backwards. All expected folder names must match
        in order, but extra parts in the actual path (like "My Drive") are ignored.
        
        Example:
            Expected: "Projects/Aideia" (from "u:\\My Drive\\Projects\\Aideia\\file.gdoc")
            Actual: "My Drive/Projects/Aideia" (from Google Drive)
            Match backwards: "Aideia" == "Aideia" ✓, "Projects" == "Projects" ✓
            Result: Match (extra "My Drive" in actual path is ignored)
        
        Args:
            expected_path: Path from filesystem like "Projects/Aideia" (after removing drive letter)
            actual_path: Full path from Google Drive like "My Drive/Projects/Aideia"
        
        Returns:
            True if all expected path parts match backwards in actual path
        """
        # Normalize paths
        expected_parts = [p.strip() for p in expected_path.split('/') if p.strip()] if expected_path else []
        actual_parts = [p.strip() for p in actual_path.split('/') if p.strip()] if actual_path else []
        
        # If expected path is empty, document should be in root
        if not expected_parts:
            # Empty expected path means root - any actual path is acceptable
            return True
        
        # If actual path is empty but expected is not, no match
        if not actual_parts:
            return False
        
        # Match backwards from the end
        expected_idx = len(expected_parts) - 1  # Start from last expected part
        actual_idx = len(actual_parts) - 1       # Start from last actual part
        
        logger.debug(f"Matching backwards - Expected: {expected_parts}, Actual: {actual_parts}")
        
        # Match folder names from end to beginning
        # Continue until all expected parts are matched
        while expected_idx >= 0:
            # If we've run out of actual parts, no match
            if actual_idx < 0:
                logger.debug(f"  ✗ Ran out of actual parts, {expected_idx + 1} expected parts remain")
                return False
            
            expected_part = expected_parts[expected_idx]
            actual_part = actual_parts[actual_idx]
            
            logger.debug(f"  Comparing: expected[{expected_idx}]='{expected_part}' vs actual[{actual_idx}]='{actual_part}'")
            
            # Compare folder names
            if expected_part == actual_part:
                logger.debug(f"  ✓ Match: '{expected_part}'")
                expected_idx -= 1
                actual_idx -= 1
            else:
                logger.debug(f"  ✗ Mismatch: '{expected_part}' != '{actual_part}'")
                return False
        
        # All expected parts matched
        logger.debug(f"  ✓ All {len(expected_parts)} expected parts matched successfully")
        return True
    
    def find_document_by_path(self, file_path: str) -> Optional[str]:
        """
        Find a Google Drive document by its filesystem path.
        
        Strategy:
        1. Search for all documents with the matching name and MIME type
        2. For each match, fetch its full folder path by traversing parents
        3. Compare the fetched path with the expected path from filesystem
        4. Return the document whose path matches
        
        Args:
            file_path: Filesystem path like "G:\\My Drive\\Projects\\Document.gdoc"
        
        Returns:
            Document ID if found and path matches, None otherwise
        """
        logger.info(f"Searching Google Drive for document: {file_path}")
        
        try:
            # Parse the path
            document_name, expected_folder_path, extension = self._parse_file_path(file_path)
            mime_type = self._get_mime_type_from_extension(extension)
            
            logger.debug(f"Parsed path - Name: '{document_name}', Expected folder: '{expected_folder_path}', Type: {mime_type}")
            
            if not mime_type:
                logger.error(f"Unknown file extension: {extension}")
                return None
            
            # Normalize expected path for comparison
            expected_path_normalized = self._normalize_path(expected_folder_path)
            logger.info(f"Searching for document '{document_name}' (type: {mime_type}), expected in folder: '{expected_path_normalized}'")
            
            # Search for all documents with this name and type (no folder constraint)
            escaped_name = document_name.replace("'", "\\'")
            query = f"name='{escaped_name}' and mimeType='{mime_type}' and trashed=false"
            
            logger.debug(f"Document search query: {query}")
            
            results = self.drive_service.files().list(
                q=query,
                fields="files(id, name, parents, mimeType)",
                pageSize=50  # Get more results to check multiple matches
            ).execute()
            
            files = results.get('files', [])
            
            if not files:
                logger.warning(f"No documents found matching name '{document_name}' (type: {mime_type})")
                return None
            
            logger.info(f"Found {len(files)} document(s) with name '{document_name}', checking paths...")
            
            # Check each document's path
            for i, file in enumerate(files, 1):
                file_id = file['id']
                file_name = file.get('name', '')
                logger.debug(f"Checking document {i}/{len(files)}: '{file_name}' (ID: {file_id})")
                
                # Get the actual folder path of this document
                actual_folder_path = self._get_file_path(file_id)
                actual_path_normalized = self._normalize_path(actual_folder_path)
                
                logger.debug(f"  Document '{file_name}' is in folder: '{actual_path_normalized}'")
                logger.debug(f"  Expected folder path: '{expected_path_normalized}'")
                
                # Compare paths using backwards matching
                if self._paths_match_backwards(expected_path_normalized, actual_path_normalized):
                    logger.info(f"✓ Path match! Found document '{file_name}' (ID: {file_id}) in folder '{actual_path_normalized}'")
                    
                    # Verify the document by fetching it directly
                    try:
                        file_info = self.drive_service.files().get(
                            fileId=file_id,
                            fields="id, name, mimeType"
                        ).execute()
                        
                        verified_name = file_info.get('name', '')
                        verified_mime = file_info.get('mimeType', '')
                        
                        logger.info(f"Verified document '{verified_name}' with ID: {file_id} (MIME: {verified_mime})")
                        return file_id
                        
                    except HttpError as e:
                        logger.error(f"Failed to verify document {file_id}: {e}")
                        # Still return the ID if path matched
                        logger.warning(f"Returning document ID despite verification failure (path matched)")
                        return file_id
                else:
                    logger.debug(f"  ✗ Path mismatch: expected path '{expected_path_normalized}' not found in actual path '{actual_path_normalized}'")
            
            logger.warning(f"None of the {len(files)} documents matched the expected path: '{expected_path_normalized}'")
            return None
            
        except HttpError as e:
            logger.error(f"Error searching Google Drive: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Error finding document by path: {e}", exc_info=True)
            return None
    
    def read_google_doc(self, document_id: str) -> str:
        """Read content from a Google Doc and convert to markdown-like text."""
        logger.info(f"Reading Google Doc: {document_id}")
        try:
            doc = self.docs_service.documents().get(documentId=document_id).execute()
            logger.debug(f"Retrieved document: {doc.get('title', 'Untitled')}")
            
            content_parts = []
            
            def extract_text(element):
                """Recursively extract text from document elements."""
                text = ""
                if 'paragraph' in element:
                    para = element['paragraph']
                    if 'elements' in para:
                        for elem in para['elements']:
                            if 'textRun' in elem:
                                text += elem['textRun'].get('content', '')
                elif 'table' in element:
                    # Handle tables
                    table = element['table']
                    if 'tableRows' in table:
                        for row in table['tableRows']:
                            row_text = []
                            if 'tableCells' in row:
                                for cell in row['tableCells']:
                                    cell_text = ""
                                    if 'content' in cell:
                                        for content_elem in cell['content']:
                                            cell_text += extract_text(content_elem)
                                    row_text.append(cell_text)
                            content_parts.append("| " + " | ".join(row_text) + " |")
                            text += "\n"
                return text
            
            if 'body' in doc and 'content' in doc['body']:
                for element in doc['body']['content']:
                    text = extract_text(element)
                    if text.strip():
                        content_parts.append(text)
            
            result = "\n".join(content_parts)
            content_length = len(result) if result.strip() else 0
            logger.info(f"Successfully read Google Doc ({content_length} characters)")
            return result if result.strip() else "Document is empty."
            
        except HttpError as e:
            logger.error(f"Error reading Google Doc {document_id}: {e}", exc_info=True)
            raise Exception(f"Error reading Google Doc: {e}")
    
    def read_google_sheet(self, document_id: str) -> str:
        """Read content from a Google Sheet and convert to text/CSV format."""
        logger.info(f"Reading Google Sheet: {document_id}")
        try:
            sheet = self.sheets_service.spreadsheets().get(spreadsheetId=document_id).execute()
            logger.debug(f"Retrieved spreadsheet: {sheet.get('properties', {}).get('title', 'Untitled')}")
            
            result_parts = []
            result_parts.append(f"Spreadsheet: {sheet.get('properties', {}).get('title', 'Untitled')}\n")
            
            # Get all sheets
            sheets = sheet.get('sheets', [])
            
            for sheet_info in sheets:
                sheet_title = sheet_info['properties']['title']
                result_parts.append(f"\n## Sheet: {sheet_title}\n")
                
                # Get values from the sheet
                range_name = f"{sheet_title}!A1:Z1000"  # Adjust range as needed
                try:
                    result = self.sheets_service.spreadsheets().values().get(
                        spreadsheetId=document_id,
                        range=range_name
                    ).execute()
                    
                    values = result.get('values', [])
                    if values:
                        # Format as table
                        for row in values:
                            # Pad row to match max columns
                            max_cols = max(len(r) for r in values) if values else 0
                            row_padded = row + [''] * (max_cols - len(row))
                            result_parts.append("| " + " | ".join(str(cell) for cell in row_padded) + " |")
                    else:
                        result_parts.append("(Empty sheet)")
                except HttpError:
                    result_parts.append("(Unable to read sheet data)")
            
            result = "\n".join(result_parts)
            logger.info(f"Successfully read Google Sheet ({len(result)} characters)")
            return result
            
        except HttpError as e:
            logger.error(f"Error reading Google Sheet {document_id}: {e}", exc_info=True)
            raise Exception(f"Error reading Google Sheet: {e}")
    
    def read_google_slides(self, document_id: str) -> str:
        """Read content from Google Slides and convert to text format."""
        logger.info(f"Reading Google Slides: {document_id}")
        try:
            presentation = self.slides_service.presentations().get(
                presentationId=document_id
            ).execute()
            logger.debug(f"Retrieved presentation: {presentation.get('title', 'Untitled')}")
            
            result_parts = []
            result_parts.append(f"Presentation: {presentation.get('title', 'Untitled')}\n")
            
            slides = presentation.get('slides', [])
            
            for i, slide in enumerate(slides, 1):
                result_parts.append(f"\n## Slide {i}\n")
                
                # Extract text from slide elements
                if 'pageElements' in slide:
                    for element in slide['pageElements']:
                        if 'shape' in element:
                            shape = element['shape']
                            if 'text' in shape and 'textElements' in shape['text']:
                                for text_elem in shape['text']['textElements']:
                                    if 'textRun' in text_elem:
                                        text = text_elem['textRun'].get('content', '')
                                        if text.strip():
                                            result_parts.append(text)
                
                result_parts.append("")  # Empty line between slides
            
            result = "\n".join(result_parts)
            logger.info(f"Successfully read Google Slides ({len(result)} characters)")
            return result
            
        except HttpError as e:
            logger.error(f"Error reading Google Slides {document_id}: {e}", exc_info=True)
            raise Exception(f"Error reading Google Slides: {e}")
    
    def export_google_document(self, document_id: str, file_type: str = "markdown") -> str:
        """
        Export a Google document to the specified format.
        
        Args:
            document_id: The Google Drive document ID
            file_type: Export format (markdown, text, csv, etc.)
        """
        # Determine document type by trying to access it
        try:
            # Try as Google Doc
            doc = self.docs_service.documents().get(documentId=document_id).execute()
            content = self.read_google_doc(document_id)
            if file_type.lower() == "markdown":
                return content  # Already in markdown-like format
            return content
        except HttpError:
            pass
        
        try:
            # Try as Google Sheet
            sheet = self.sheets_service.spreadsheets().get(spreadsheetId=document_id).execute()
            content = self.read_google_sheet(document_id)
            if file_type.lower() == "csv":
                # Convert to CSV format
                lines = content.split('\n')
                csv_lines = []
                for line in lines:
                    if line.startswith('|') and line.endswith('|'):
                        # Convert markdown table to CSV
                        cells = [cell.strip() for cell in line[1:-1].split('|')]
                        csv_lines.append(','.join(f'"{cell}"' for cell in cells))
                return '\n'.join(csv_lines)
            return content
        except HttpError:
            pass
        
        try:
            # Try as Google Slides
            content = self.read_google_slides(document_id)
            return content
        except HttpError:
            pass
        
        raise Exception(f"Unable to determine document type for ID: {document_id}")


# Global client instance (initialized on first use)
_drive_client: Optional[GoogleDriveClient] = None


def get_drive_client() -> GoogleDriveClient:
    """Get or create the Google Drive client instance."""
    global _drive_client
    if _drive_client is None:
        _drive_client = GoogleDriveClient()
    return _drive_client


@app.list_tools()
async def list_tools() -> List[Tool]:
    """
    List available tools that the server can execute.
    """
    return [
        Tool(
            name="read_google_doc",
            description="Read content from a Google Doc (.gdoc) file accessible via the Windows virtual drive. REQUIRES THE FULL FILESYSTEM PATH, not just the filename. The path must include the drive letter, folder structure, and filename (e.g., 'G:\\My Drive\\Projects\\Document.gdoc').",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_name_in_filesystem": {
                        "type": "string",
                        "description": "REQUIRED: The FULL filesystem path to the .gdoc file, including drive letter and all folder names. Example: 'G:\\My Drive\\Projects\\Aideia\\Document.gdoc' or 'u:\\My Drive\\Folder\\Subfolder\\MyDocument.gdoc'. Do NOT provide just the filename - the complete path is required.",
                    }
                },
                "required": ["document_name_in_filesystem"],
            },
        ),
        Tool(
            name="read_google_sheets",
            description="Read content from a Google Sheet (.gsheet) file accessible via the Windows virtual drive. REQUIRES THE FULL FILESYSTEM PATH, not just the filename. The path must include the drive letter, folder structure, and filename (e.g., 'G:\\My Drive\\Projects\\Spreadsheet.gsheet').",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_name_in_filesystem": {
                        "type": "string",
                        "description": "REQUIRED: The FULL filesystem path to the .gsheet file, including drive letter and all folder names. Example: 'G:\\My Drive\\Projects\\Aideia\\Spreadsheet.gsheet' or 'u:\\My Drive\\Folder\\Subfolder\\MySheet.gsheet'. Do NOT provide just the filename - the complete path is required.",
                    }
                },
                "required": ["document_name_in_filesystem"],
            },
        ),
        Tool(
            name="read_google_slides",
            description="Read content from a Google Slides (.gslides) file accessible via the Windows virtual drive. REQUIRES THE FULL FILESYSTEM PATH, not just the filename. The path must include the drive letter, folder structure, and filename (e.g., 'G:\\My Drive\\Projects\\Presentation.gslides').",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_name_in_filesystem": {
                        "type": "string",
                        "description": "REQUIRED: The FULL filesystem path to the .gslides file, including drive letter and all folder names. Example: 'G:\\My Drive\\Projects\\Aideia\\Presentation.gslides' or 'u:\\My Drive\\Folder\\Subfolder\\MySlides.gslides'. Do NOT provide just the filename - the complete path is required.",
                    }
                },
                "required": ["document_name_in_filesystem"],
            },
        ),
        Tool(
            name="export_google_document",
            description="Export a Google Drive document (.gdoc, .gsheet, or .gslides) to markdown or other formats. REQUIRES THE FULL FILESYSTEM PATH, not just the filename. The path must include the drive letter, folder structure, and filename.",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_name_in_filesystem": {
                        "type": "string",
                        "description": "REQUIRED: The FULL filesystem path to the Google Drive document file, including drive letter and all folder names. Example: 'G:\\My Drive\\Projects\\Aideia\\Document.gdoc' or 'u:\\My Drive\\Folder\\Subfolder\\MyDocument.gdoc'. Do NOT provide just the filename - the complete path is required.",
                    },
                    "format": {
                        "type": "string",
                        "description": "Export format: 'markdown', 'text', 'csv' (for sheets). Default: 'markdown'",
                        "enum": ["markdown", "text", "csv"],
                        "default": "markdown",
                    },
                },
                "required": ["document_name_in_filesystem"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """
    Execute a tool by name with the provided arguments.
    """
    logger.info(f"Tool called: {name} with arguments: {arguments}")
    try:
        client = get_drive_client()
        document_path = arguments.get("document_name_in_filesystem", "")
        
        if not document_path:
            error_msg = "document_name_in_filesystem is required"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.info(f"Processing document: {document_path}")
        # Find document in Google Drive by name and path
        document_id = client.find_document_by_path(document_path)
        
        if not document_id:
            error_msg = (
                f"Could not find document in Google Drive: {document_path}. "
                "Make sure the document exists in your Google Drive and you have access to it."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.info(f"Extracted document ID: {document_id}")
        
        if name == "read_google_doc":
            if not document_path.lower().endswith('.gdoc'):
                error_msg = "File must be a .gdoc file"
                logger.error(error_msg)
                raise ValueError(error_msg)
            content = client.read_google_doc(document_id)
            logger.info(f"Successfully read Google Doc, returning {len(content)} characters")
            return [
                TextContent(
                    type="text",
                    text=f"Google Doc Content:\n\n{content}",
                )
            ]
        
        elif name == "read_google_sheets":
            if not document_path.lower().endswith('.gsheet'):
                error_msg = "File must be a .gsheet file"
                logger.error(error_msg)
                raise ValueError(error_msg)
            content = client.read_google_sheet(document_id)
            logger.info(f"Successfully read Google Sheet, returning {len(content)} characters")
            return [
                TextContent(
                    type="text",
                    text=f"Google Sheet Content:\n\n{content}",
                )
            ]
        
        elif name == "read_google_slides":
            if not document_path.lower().endswith('.gslides'):
                error_msg = "File must be a .gslides file"
                logger.error(error_msg)
                raise ValueError(error_msg)
            content = client.read_google_slides(document_id)
            logger.info(f"Successfully read Google Slides, returning {len(content)} characters")
            return [
                TextContent(
                    type="text",
                    text=f"Google Slides Content:\n\n{content}",
                )
            ]
        
        elif name == "export_google_document":
            export_format = arguments.get("format", "markdown")
            logger.info(f"Exporting document to {export_format} format")
            content = client.export_google_document(document_id, export_format)
            logger.info(f"Successfully exported document, returning {len(content)} characters")
            return [
                TextContent(
                    type="text",
                    text=f"Exported Document ({export_format}):\n\n{content}",
                )
            ]
        
        else:
            error_msg = f"Unknown tool: {name}"
            logger.error(error_msg)
            raise ValueError(error_msg)
    
    except Exception as e:
        error_msg = f"Error executing tool '{name}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [
            TextContent(
                type="text",
                text=error_msg,
            )
        ]


async def main():
    """
    Main entry point for the MCP server.
    """
    logger.info("Starting Google Drive MCP Server...")
    logger.info(f"Log level: {LOG_LEVEL}, Log file: {LOG_FILE}")
    # Run the server using stdio transport
    try:
        async with stdio_server() as (read_stream, write_stream):
            logger.info("MCP server initialized, waiting for requests...")
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )
    except Exception as e:
        logger.critical(f"Fatal error in MCP server: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    logger.info("Launching Google Drive MCP Server...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.critical(f"Server crashed: {e}", exc_info=True)
        sys.exit(1)
