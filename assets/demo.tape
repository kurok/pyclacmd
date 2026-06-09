# vhs tape for the README demo GIF (interactive mode).
# Regenerate with:  cd <repo> && vhs assets/demo.tape
# Requires `vhs`, an authenticated `claude` on PATH, and `claudecmd` installed
# on PATH (pip install pyclacmd).

Output assets/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1180
Set Height 540
Set Padding 18
Set Theme "Dracula"
Set TypingSpeed 32ms
Set Framerate 24

Hide
Type 'export PATH="$HOME/.local/bin:$PATH"'
Enter
Type "export PS1='$ '"
Enter
Type 'mkdir -p /tmp/ccdemo && cd /tmp/ccdemo && clear'
Enter
Show

Sleep 700ms
Type '# claudecmd drives Claude Code interactive session (no -p, stays on your subscription)'
Sleep 400ms
Enter
Type 'claudecmd "Give a one-line shell command to count files in the current directory. Output only the command."'
Sleep 400ms
Enter
Sleep 14s

Type '# pipe stdin in as context'
Sleep 400ms
Enter
Type 'echo "the cat sat on the mat" | claudecmd "Translate to French. Output only the sentence."'
Sleep 400ms
Enter
Sleep 14s

Type '# stable JSON envelope; --dry-run shows the interactive command (note: no -p)'
Sleep 400ms
Enter
Type 'claudecmd --dry-run --json "review this repo"'
Sleep 400ms
Enter
Sleep 3s
