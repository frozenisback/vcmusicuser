#!/bin/bash
# Create the fonts directory if it doesn't exist
mkdir -p ~/.local/share/fonts
# Download the Arial font
wget https://github.com/gasharper/linux-fonts/raw/master/arial.ttf -O ~/.local/share/fonts/arial.ttf
# Update the font cache
fc-cache -f -v
