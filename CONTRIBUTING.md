# Contributing to Cynthia AI Assistant

First off, thank you for considering contributing to Cynthia AI Assistant! It is people like you who make the open-source community such an amazing place to learn, inspire, and create.

## Code of Conduct

This project and everyone participating in it is governed by the [Cynthia Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## How Can I Contribute?

### Reporting Bugs

If you find a bug, please open an issue using the Bug Report template. Include:
- A clear and descriptive title.
- Steps to reproduce the behavior.
- Details about your environment (OS, Python version, dependencies).
- Any relevant logs or screen captures.

### Suggesting Enhancements

If you have an idea for a new feature or improvement:
- Open an issue using the Feature Request template.
- Explain the behavior you would like to see and why it is useful.
- Provide examples or mockups where applicable.

### Pull Requests

To submit code changes:
1. Fork the repository and create your branch from `main`.
2. Install dependencies via `pip install -r requirement.txt`.
3. If you add code, add clean comments and ensure it doesn't break existing features.
4. Run syntax checks:
   ```bash
   python -m py_compile agent.py prompts.py
   ```
5. Run tests:
   ```bash
   pytest
   ```
6. Submit a pull request using the Pull Request template.

## Development Setup

1. Clone your fork:
   ```bash
   git clone https://github.com/your-username/femle-best-friend.git
   cd femle-best-friend
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirement.txt
   ```
4. Set up your local configuration:
   ```bash
   copy .env.example .env
   # Edit .env with your local credentials
   ```
