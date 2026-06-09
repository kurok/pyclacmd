# vhs tape for the README demo GIF.
# Regenerate with:  cd <repo> && vhs assets/demo.tape
# (requires `vhs`, an authenticated `claude` on PATH, and the claudecmd shim)

Output assets/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1180
Set Height 520
Set Padding 18
Set Theme "Dracula"
Set TypingSpeed 32ms
Set Framerate 24

Hide
Type 'export PATH="$HOME/.local/bin:/tmp/pyclacmd/bin:$PATH"'
Enter
Type "export PS1='$ '"
Enter
Type 'mkdir -p /tmp/ccdemo && cd /tmp/ccdemo && clear'
Enter
Show

Sleep 700ms
Type '# ask Claude Code straight from the shell'
Sleep 400ms
Enter
Type 'claudecmd "Give a one-line shell command to count files in the current directory. Output only the command, no backticks."'
Sleep 400ms
Enter
Sleep 9s

Type '# pipe stdin in as context'
Sleep 400ms
Enter
Type 'echo "the cat sat on the mat" | claudecmd "Translate to French. Output only the sentence."'
Sleep 400ms
Enter
Sleep 9s

Type '# stable JSON contract; --dry-run previews the command without calling Claude'
Sleep 400ms
Enter
Type 'claudecmd --dry-run --json "review this repo"'
Sleep 400ms
Enter
Sleep 3s
