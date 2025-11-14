# Google Drive MCP Server for Gemini CLI / Windows

An MCP (Model Context Protocol) server that enables Google Gemini CLI to access and read Google Drive documents (`.gdoc`, `.gsheet`, `.gslides`) that are accessible via the Windows Google Drive virtual drive.

## Overview

When using Google Drive for Windows, Google Drive and shared folders are made available through a virtual drive that can be navigated like a local file system. However, Google Gemini CLI cannot directly access the content within Google Drive documents (`.gsheet`, `.gdoc`, `.gslides`) like it can with native formats (`.docx`, `.xlsx`, `.pptx`).

This MCP server bridges that gap by:
- Parsing filesystem paths to extract document names and folder paths
- Searching Google Drive for documents matching the name and path
- Using the Google Drive API to fetch document content
- Converting documents to readable formats (markdown, text, CSV)
- Making the content available to Google Gemini CLI

## Features

- **Read Google Docs** (`.gdoc`): Extract and convert Google Docs to markdown/text format
- **Read Google Sheets** (`.gsheet`): Extract and convert Google Sheets to table/text format
- **Read Google Slides** (`.gslides`): Extract and convert Google Slides to text format
- **Export Documents**: Export Google Drive documents to various formats (markdown, text, CSV)

## Prerequisites

1. **Python 3.8+**
2. **Google Cloud Project** with the following APIs enabled:
   - Google Drive API
   - Google Docs API
   - Google Sheets API
   - Google Slides API
3. **OAuth2 Credentials**: You need to create OAuth2 credentials in the Google Cloud Console

## Installation

1. Install the required dependencies:

```bash
pip install -r requirements.txt
```

2. Set up Google OAuth2 credentials:

   a. Go to [Google Cloud Console](https://console.cloud.google.com/)
   
   b. Create a new project or select an existing one
   
   c. Enable the required APIs:
      - Google Drive API
      - Google Docs API
      - Google Sheets API
      - Google Slides API
   
   d. Go to "Credentials" → "Create Credentials" → "OAuth client ID"
   
   e. Choose "Desktop app" as the application type
   
   f. Copy the **Client ID** and **Client Secret** (or download the credentials JSON file)

## Configuration

### For Google Gemini CLI

Add the MCP server to your Gemini CLI configuration. The configuration format depends on your setup, but typically looks like this:

#### Option 1: Using OAuth Client ID and Secret (Recommended)

This is the simplest method - just provide your OAuth client ID and secret:

```json
{
  "mcpServers": {
    "google-drive-mcp": {
      "command": "python",
      "args": ["server.py"],
      "cwd": "path/to/gemini-cli-gdrive-mcp",
      "env": {
        "GOOGLE_CLIENT_ID": "your-client-id.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "your-client-secret",
        "MCP_LOG_LEVEL": "DEBUG",
        "MCP_LOG_FILE": "mcp_server.log"
      },
      "timeout": 30000,
      "trust": true
    }
  }
}
```

#### Option 2: Using Credentials JSON File

You can also use a credentials JSON file:

```json
{
  "mcpServers": {
    "google-drive-mcp": {
      "command": "python",
      "args": ["server.py"],
      "cwd": "path/to/gemini-cli-gdrive-mcp",
      "env": {
        "GOOGLE_CREDENTIALS": "path/to/credentials.json",
        "MCP_LOG_LEVEL": "DEBUG",
        "MCP_LOG_FILE": "mcp_server.log"
      },
      "timeout": 30000,
      "trust": true
    }
  }
}
```

#### Option 3: Using Credentials JSON String

If you prefer to pass credentials as a JSON string:

```json
{
  "mcpServers": {
    "google-drive-mcp": {
      "command": "python",
      "args": ["server.py"],
      "cwd": "path/to/gemini-cli-gdrive-mcp",
      "env": {
        "GOOGLE_CREDENTIALS": "{\"installed\":{\"client_id\":\"...\",\"client_secret\":\"...\",\"auth_uri\":\"...\",\"token_uri\":\"...\",\"auth_provider_x509_cert_url\":\"...\",\"redirect_uris\":[\"...\"]}}"
      },
      "timeout": 30000,
      "trust": true
    }
  }
}
```

### Environment Variables

The server uses the following environment variables (in order of preference):

**OAuth Credentials (choose one method):**
- **`GOOGLE_CLIENT_ID`** and **`GOOGLE_CLIENT_SECRET`** (recommended): OAuth2 client ID and secret from Google Cloud Console
- **`GOOGLE_CREDENTIALS`**: Path to your OAuth2 credentials JSON file, or a JSON string containing the credentials

**Other Settings:**
- **`GOOGLE_TOKEN_PATH`** (optional): Path where to store the OAuth2 token. Default: `token.json`
- **`MCP_LOG_LEVEL`** (optional): Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). Default: `INFO`
- **`MCP_LOG_FILE`** (optional): Path to the log file. Default: `mcp_server.log`

## Usage

Once configured, the MCP server provides the following tools to Google Gemini CLI:

### Tools

1. **`read_google_doc`**
   - Reads content from a Google Doc (`.gdoc`) file
   - Converts to markdown-like text format
   - Example: `read_google_doc("G:\\My Drive\\MyDocument.gdoc")`

2. **`read_google_sheets`**
   - Reads content from a Google Sheet (`.gsheet`) file
   - Converts to table/text format
   - Example: `read_google_sheets("G:\\My Drive\\MySpreadsheet.gsheet")`

3. **`read_google_slides`**
   - Reads content from Google Slides (`.gslides`) file
   - Converts to text format with slide structure
   - Example: `read_google_slides("G:\\My Drive\\MyPresentation.gslides")`

4. **`export_google_document`**
   - Exports a Google Drive document to various formats
   - Supports: `markdown`, `text`, `csv` (for sheets)
   - Example: `export_google_document("G:\\My Drive\\MyDocument.gdoc", format="markdown")`

## First-Time Authentication

On first run, the server will:
1. Open a browser window for OAuth2 authentication
2. Ask you to sign in with your Google account
3. Request permissions to access your Google Drive
4. Save the authentication token for future use

The token is saved to `token.json` (or the path specified in `GOOGLE_TOKEN_PATH`).

## Logging and Debugging

The MCP server includes comprehensive logging to help you monitor its activity and debug issues. Logs are written to both:

1. **stderr** - May be visible in some CLI configurations
2. **Log file** - Always accessible (default: `mcp_server.log`)

### Viewing Logs

To view the server logs, check the log file:

```bash
# View the log file
cat mcp_server.log

# Or on Windows
type mcp_server.log

# Follow logs in real-time (if tail is available)
tail -f mcp_server.log
```

### Log Levels

Control logging verbosity using the `MCP_LOG_LEVEL` environment variable:

- **`DEBUG`**: Detailed information for diagnosing problems
- **`INFO`**: General informational messages (default)
- **`WARNING`**: Warning messages for potential issues
- **`ERROR`**: Error messages for failures
- **`CRITICAL`**: Only critical errors

The log file will contain detailed information about:
- Server startup and initialization
- Authentication attempts and token management
- Document ID extraction from files
- API calls to Google Drive services
- Tool execution and results
- Errors and exceptions with full stack traces

## How It Works

1. **Path Parsing**: The server parses the filesystem path (e.g., `u:\My Drive\Projects\Project A\Document.gdoc`) to extract:
   - Document name (without extension)
   - Folder path
   - Document type (from file extension)
   
   For example, `u:\My Drive\Projects\Project A\Document.gdoc` becomes:
   - Document name: `Document`
   - Folder path: `My Drive/Projects/Project A`
   - Type: `.gdoc`

2. **Google Drive Search**: Since virtual drive files can't be read directly, the server:
   - Searches Google Drive for documents matching the name and type
   - Checks every found document with the correct name and type against the path to make sure it's the correct one
   - Retrieves the contents of the document that matches the path on the Google Drive folder on your pc.

3. **API Access**: Uses the Google Drive API to fetch the actual document content using the document ID.

4. **Format Conversion**: Converts the document content to readable formats:
   - Google Docs → Markdown/Text
   - Google Sheets → Table/CSV format
   - Google Slides → Text with slide structure

5. **Content Delivery**: Returns the converted content to Google Gemini CLI for use in conversations.

## Troubleshooting

### Authentication Issues

- **"Google OAuth credentials not provided"**: 
  - Set either `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` environment variables, or
  - Set `GOOGLE_CREDENTIALS` environment variable with the path to credentials.json or a JSON string
- **"Invalid credentials"**: Verify your OAuth client ID and secret are correct, or that your credentials JSON file is valid and properly formatted
- **Token refresh errors**: Delete `token.json` and re-authenticate

### Document Access Issues

- **"Could not find document in Google Drive"**: 
  - Ensure the document name in the path matches exactly (case-sensitive)
  - Verify the folder path is correct (the path after "My Drive" should match your Google Drive folder structure)
  - Check that you have access to the document in Google Drive and that you are in the right Google account!!! (ask me how I know)


- **"Error reading Google Doc/Sheet/Slides"**:
  - Verify you have the necessary permissions to access the document
  - Check that the required APIs are enabled in your Google Cloud project
  - Ensure your OAuth2 credentials have the correct scopes

## Project Structure

```
.
├── server.py          # Main MCP server implementation
├── requirements.txt   # Python dependencies
├── README.md         # This file
├── .gitignore        # Git ignore file
```

## Security Notes

- **Never commit `token.json` or `credentials.json` to version control**
- The `.gitignore` file is configured to exclude these files
- Keep your OAuth2 credentials secure
- The server only requests read-only access to your Google Drive

## License

This project is provided as-is for educational and development purposes.

## References

- [Google Gemini CLI MCP Documentation](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md)
- [Google Drive API Documentation](https://developers.google.com/drive/api)
- [Google Docs API Documentation](https://developers.google.com/docs/api)
- [Google Sheets API Documentation](https://developers.google.com/sheets/api)
- [Google Slides API Documentation](https://developers.google.com/slides/api)
