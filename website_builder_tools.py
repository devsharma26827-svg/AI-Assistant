"""
Website Builder Tools for Cynthia AI Assistant.
Generates responsive, accessible, multi-section website templates in dedicated project directories,
with semantic HTML5, modern CSS (Flexbox/Grid), JavaScript interactivity, and browser preview.
"""
import os
import re
import logging
import webbrowser
from livekit.agents import function_tool

logger = logging.getLogger("website_builder_tools")
logger.setLevel(logging.INFO)

# Base directory for generated websites
OUTPUT_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "generated_websites"))


def _clean_project_name(name: str) -> str:
    """Sanitizes project folder name to prevent path traversal or invalid characters."""
    clean = re.sub(r'[^a-zA-Z0-9_\-]', '_', (name or "my_website").strip())
    return clean or "my_website"


@function_tool
async def build_website_template(
    project_name: str,
    description: str,
    layout_type: str = "responsive",
    style_framework: str = "vanilla_css",
    include_canvas: bool = False
) -> str:
    """
    Builds a complete, responsive website template project with HTML5, CSS, and JavaScript.
    
    Parameters:
    - project_name: Name of the project folder (e.g., 'portfolio', 'coffee_shop', 'saas_landing').
    - description: Description of the website, branding, pages, colors, and features.
    - layout_type: 'responsive' (default), 'single_page', 'dashboard', 'landing_page'.
    - style_framework: 'vanilla_css' (default) or 'tailwind'.
    - include_canvas: Whether to include an interactive HTML5 Canvas element.
    """
    clean_name = _clean_project_name(project_name)
    project_dir = os.path.join(OUTPUT_BASE_DIR, clean_name)
    
    os.makedirs(project_dir, exist_ok=True)
    
    title = clean_name.replace("_", " ").title()
    desc_snippet = description.strip() if description else f"Modern {title} Website"

    # 1. HTML5 Structure
    tailwind_script = '<script src="https://cdn.tailwindcss.com"></script>' if style_framework.lower() == "tailwind" else ""
    css_link = '<link rel="stylesheet" href="style.css">' if style_framework.lower() != "tailwind" else ""
    
    canvas_markup = """
        <section class="section canvas-section">
            <div class="container">
                <h2>Interactive Canvas</h2>
                <canvas id="interactiveCanvas" width="600" height="300"></canvas>
            </div>
        </section>
    """ if include_canvas else ""

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{desc_snippet}">
    <title>{title}</title>
    {tailwind_script}
    {css_link}
</head>
<body class="bg-gray-50 text-gray-900 font-sans">
    <!-- Navigation Bar -->
    <header class="header">
        <nav class="navbar">
            <div class="logo"><strong>{title}</strong></div>
            <ul class="nav-links" id="navLinks">
                <li><a href="#home">Home</a></li>
                <li><a href="#features">Features</a></li>
                <li><a href="#about">About</a></li>
                <li><a href="#contact">Contact</a></li>
            </ul>
            <button class="nav-toggle" id="navToggle" aria-label="Toggle navigation">&#9776;</button>
        </nav>
    </header>

    <!-- Hero Section -->
    <main>
        <section id="home" class="hero">
            <div class="hero-content">
                <h1>Welcome to {title}</h1>
                <p>{desc_snippet}</p>
                <a href="#contact" class="btn btn-primary">Get Started</a>
            </div>
        </section>

        <!-- Features Section -->
        <section id="features" class="section">
            <div class="container">
                <h2>Our Features</h2>
                <div class="grid-cards">
                    <div class="card">
                        <h3>Fast & Responsive</h3>
                        <p>Designed with mobile-first modern CSS Flexbox and Grid layout.</p>
                    </div>
                    <div class="card">
                        <h3>Accessible</h3>
                        <p>Built with semantic HTML5 elements and accessible UI patterns.</p>
                    </div>
                    <div class="card">
                        <h3>Interactive</h3>
                        <p>Clean vanilla JavaScript for dynamic behavior and client validation.</p>
                    </div>
                </div>
            </div>
        </section>

        {canvas_markup}

        <!-- Contact Section with Form Validation -->
        <section id="contact" class="section">
            <div class="container">
                <h2>Contact Us</h2>
                <form id="contactForm" class="contact-form" novalidate>
                    <div class="form-group">
                        <label for="name">Name:</label>
                        <input type="text" id="name" name="name" required placeholder="Aapka naam">
                    </div>
                    <div class="form-group">
                        <label for="email">Email:</label>
                        <input type="email" id="email" name="email" required placeholder="name@example.com">
                    </div>
                    <div class="form-group">
                        <label for="message">Message:</label>
                        <textarea id="message" name="message" rows="4" required placeholder="Aapka sandesh..."></textarea>
                    </div>
                    <button type="submit" class="btn btn-primary">Send Message</button>
                    <p id="formStatus" class="form-status" aria-live="polite"></p>
                </form>
            </div>
        </section>
    </main>

    <!-- Footer -->
    <footer class="footer">
        <p>&copy; 2026 {title}. Built with Cynthia AI Assistant.</p>
    </footer>

    <script src="app.js"></script>
</body>
</html>
"""

    # 2. Modern Responsive CSS
    css_content = """/* Modern Clean Stylesheet */
:root {
    --primary: #4F46E5;
    --primary-hover: #4338CA;
    --text: #1F2937;
    --bg-light: #F9FAFB;
    --card-bg: #FFFFFF;
    --border: #E5E7EB;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: var(--text);
    background-color: var(--bg-light);
    line-height: 1.6;
}

.container {
    max-width: 1100px;
    margin: 0 auto;
    padding: 0 1.5rem;
}

/* Header & Navbar */
.header {
    background: #FFFFFF;
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 50;
}

.navbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    max-width: 1100px;
    margin: 0 auto;
    padding: 1rem 1.5rem;
}

.nav-links {
    display: flex;
    list-style: none;
    gap: 1.5rem;
}

.nav-links a {
    text-decoration: none;
    color: var(--text);
    font-weight: 500;
    transition: color 0.2s;
}

.nav-links a:hover {
    color: var(--primary);
}

.nav-toggle {
    display: none;
    background: none;
    border: none;
    font-size: 1.5rem;
    cursor: pointer;
}

/* Hero */
.hero {
    background: linear-gradient(135deg, #EEF2FF 0%, #E0E7FF 100%);
    padding: 5rem 1.5rem;
    text-align: center;
}

.hero h1 {
    font-size: 2.75rem;
    margin-bottom: 1rem;
    color: #111827;
}

.hero p {
    font-size: 1.25rem;
    color: #4B5563;
    max-width: 600px;
    margin: 0 auto 2rem;
}

.btn {
    display: inline-block;
    padding: 0.75rem 1.75rem;
    font-size: 1rem;
    font-weight: 600;
    border-radius: 0.5rem;
    cursor: pointer;
    text-decoration: none;
    border: none;
    transition: background-color 0.2s;
}

.btn-primary {
    background-color: var(--primary);
    color: #FFFFFF;
}

.btn-primary:hover {
    background-color: var(--primary-hover);
}

/* Sections & Grid */
.section {
    padding: 4rem 0;
}

.section h2 {
    text-align: center;
    font-size: 2rem;
    margin-bottom: 2.5rem;
}

.grid-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 2rem;
}

.card {
    background: var(--card-bg);
    padding: 2rem;
    border-radius: 0.75rem;
    border: 1px solid var(--border);
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.card h3 {
    margin-bottom: 0.5rem;
    color: var(--primary);
}

/* Canvas */
#interactiveCanvas {
    display: block;
    margin: 1.5rem auto;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    background: #FFFFFF;
}

/* Contact Form */
.contact-form {
    max-width: 500px;
    margin: 0 auto;
    background: var(--card-bg);
    padding: 2rem;
    border-radius: 0.75rem;
    border: 1px solid var(--border);
}

.form-group {
    margin-bottom: 1.25rem;
}

.form-group label {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 500;
}

.form-group input, .form-group textarea {
    width: 100%;
    padding: 0.75rem;
    border: 1px solid var(--border);
    border-radius: 0.375rem;
    font-size: 1rem;
}

.form-status {
    margin-top: 1rem;
    font-weight: 500;
}

/* Footer */
.footer {
    background: #111827;
    color: #9CA3AF;
    text-align: center;
    padding: 2rem 1.5rem;
    margin-top: 4rem;
}

/* Mobile Responsive */
@media (max-width: 768px) {
    .nav-toggle {
        display: block;
    }
    .nav-links {
        display: none;
        flex-direction: column;
        width: 100%;
        margin-top: 1rem;
    }
    .nav-links.active {
        display: flex;
    }
}
"""

    # 3. JavaScript Interactivity
    js_content = """// Interactive scripts for navigation, validation, and canvas
document.addEventListener('DOMContentLoaded', () => {
    // 1. Mobile Navigation Toggle
    const navToggle = document.getElementById('navToggle');
    const navLinks = document.getElementById('navLinks');
    if (navToggle && navLinks) {
        navToggle.addEventListener('click', () => {
            navLinks.classList.toggle('active');
        });
    }

    // 2. Client-side Form Validation
    const contactForm = document.getElementById('contactForm');
    const formStatus = document.getElementById('formStatus');
    if (contactForm && formStatus) {
        contactForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const name = document.getElementById('name').value.trim();
            const email = document.getElementById('email').value.trim();
            const message = document.getElementById('message').value.trim();

            if (!name || !email || !message) {
                formStatus.textContent = '❌ Kripya sabhi fields fill karein.';
                formStatus.style.color = '#EF4444';
                return;
            }

            if (!email.includes('@') || !email.includes('.')) {
                formStatus.textContent = '❌ Valid email address enter karein.';
                formStatus.style.color = '#EF4444';
                return;
            }

            formStatus.textContent = '✅ Thank you! Aapka message receive ho gaya hai.';
            formStatus.style.color = '#10B981';
            contactForm.reset();
        });
    }

    // 3. HTML5 Canvas Animation (if present)
    const canvas = document.getElementById('interactiveCanvas');
    if (canvas && canvas.getContext) {
        const ctx = canvas.getContext('2d');
        let angle = 0;
        function draw() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = '#4F46E5';
            ctx.beginPath();
            const x = canvas.width / 2 + Math.cos(angle) * 80;
            const y = canvas.height / 2 + Math.sin(angle) * 40;
            ctx.arc(x, y, 20, 0, Math.PI * 2);
            ctx.fill();
            angle += 0.03;
            requestAnimationFrame(draw);
        }
        draw();
    }
});
"""

    # 4. README with instructions
    readme_content = f"""# {title}

{desc_snippet}

## Structure
- `index.html`: Semantic, responsive markup.
- `style.css`: Modern responsive styles (CSS Flexbox/Grid).
- `app.js`: Navigation toggle, contact form validation, and canvas interactions.

## Previewing Locally
Double-click `index.html` or ask Cynthia:
*"Preview website {clean_name}"*
"""

    try:
        with open(os.path.join(project_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(html_content)
        with open(os.path.join(project_dir, "style.css"), "w", encoding="utf-8") as f:
            f.write(css_content)
        with open(os.path.join(project_dir, "app.js"), "w", encoding="utf-8") as f:
            f.write(js_content)
        with open(os.path.join(project_dir, "README.md"), "w", encoding="utf-8") as f:
            f.write(readme_content)

        return (
            f"✅ Boss, '{title}' website template successfully generate ho gaya hai!\n"
            f"- Directory: `{project_dir}`\n"
            f"- Files created: `index.html`, `style.css`, `app.js`, `README.md`\n"
            f"- Features: Semantic HTML5, Responsive Flexbox/Grid, Form validation"
            f"{', HTML5 Canvas' if include_canvas else ''}\n"
            f"Aap `preview_website('{clean_name}')` bol kar ise browser mein direct dekh sakte hain."
        )
    except Exception as e:
        logger.error(f"Error building website: {e}")
        return f"❌ Website template build karne mein error aaya: {e}"


@function_tool
async def preview_website(project_name: str) -> str:
    """
    Opens the generated website's index.html in the default web browser.
    
    Parameters:
    - project_name: Name of the project folder.
    """
    clean_name = _clean_project_name(project_name)
    target_path = os.path.join(OUTPUT_BASE_DIR, clean_name, "index.html")
    
    if not os.path.exists(target_path):
        return f"❌ Project '{clean_name}' ka index.html nahi mila. Kripya pehle `build_website_template` run karein."

    try:
        webbrowser.open(f"file:///{os.path.abspath(target_path)}", new=2)
        return f"✅ Boss, '{clean_name}' website aapke browser mein open kar di hai."
    except Exception as e:
        logger.error(f"Failed to preview website: {e}")
        return f"❌ Browser open karne mein error aaya: {e}"
