from setuptools import setup

APP = ['src/main.py']
DATA_FILES = [
    ('assets', ['assets/app.icns']),
    ('src/prompts', ['src/prompts/summarize_dialog.txt']),
]
OPTIONS = {
    'argv_emulation': True,
    'iconfile': 'assets/app.icns',
    'plist': {
        'CFBundleName': "TiG Reader",
        'CFBundleDisplayName': "TiG Reader",
        'CFBundleGetInfoString': "Screen reader with AI-powered summarization",
        'CFBundleIdentifier': "com.tig.reader",
        'CFBundleVersion': "1.0.0",
        'CFBundleShortVersionString': "1.0.0",
        'LSEnvironment': {
            'PYTHONPATH': '@executable_path/../Resources/lib/python3.9/site-packages'
        }
    },
    'packages': ['PyQt6', 'openai', 'elevenlabs', 'watchdog', 'dotenv', 'PIL', 'mss'],
}

setup(
    name="TiG Reader",
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
