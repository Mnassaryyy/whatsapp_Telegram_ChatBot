# Make all scripts executable mn
chmod +x ~/scripts/*.sh

#Add scripts folder to PATH:
echo 'export PATH="$PATH:$HOME/scripts"' >> ~/.bashrc
source ~/.bashrc

