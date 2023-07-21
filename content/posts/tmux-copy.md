---
title: "Copying and pasting from tmux"
date: 2023-07-03T16:17:53Z
---
Why is coping and pasting from tmux so utterly shit? Like to literally just get the command I typed I need to remember some arcane enchantment involving `ctrl+b` (referred to helpfully only as the "prefix" on stack overflow) followed by some sort for closing bracket, or is it opening? - quick google - ok its `[`. Now we're in "copy mode" and we can use some esoteric movement keys to attempt to highlight my text. And to actually copy it? I suppose you might try `c` for copy, or perhaps `y` for yank, but no, its neither of these, it is of course `ctrl+space`.

And that's the simple case. Just imagine if you're trying to copy something out of vim *inside* tmux. Well, anyway, I'm writing this because I just found a few lines to add to your `.tmux.conf` that will revolutionise your life:

```
setw -g mouse on
set -g set-clipboard on
bind-key -T copy-mode-vi y send -X copy-pipe-and-cancel 'xclip -selection clipboard -in'
bind -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel  'xclip -selection clipboard -in'
```

Copy that in and you'll be able to just highlight it *with your mouse* and as soon as you let go, its automatically in your clipboard. Hope that it works for you too!

