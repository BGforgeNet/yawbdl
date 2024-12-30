#!/bin/sh
#
# Based on https://github.com/Robotizing/MiceWeb/blob/8b62b57e14fe8a7d6404f336a31f822d6a3efe64/install.sh

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"

bin="$INSTALL_DIR/yawbdl.py"
binpaths="/usr/local/bin /usr/bin"

is_write_perm_missing=""

cd "$INSTALL_DIR"

for binpath in $binpaths; do
	cp --no-clobber "$binpath/yawbdl.py" "$binpath/yawbdl.py.bak" 2>/dev/null
	if cp "$bin" "$binpath/yawbdl.py" 2>/dev/null; then
		echo "Copied $bin to $binpath"
		if python --version; then
			if pip install -r requirements.txt >/dev/null; then
				echo "Installed required Python components:"
			else
				echo "Need to install required Python components:"
			fi
			cat requirements.txt
			echo "Run 'yawbdl.py' in the terminal"
			exit 0
		else
			echo "Install Python and run this installation script again"
			exit 1
		fi
	else
		if [ -e "$binpath/yawbdl.py" ]; then
			echo "Check '$binpath/yawbdl.py', move it to other place and run '$0' again"
			exit 1
		fi
		if [ -d "$binpath" -a ! -w "$binpath" ]; then
			is_write_perm_missing=1
		fi
	fi
done

echo "We cannot install $bin in $binpaths"

if [ -n "$is_write_perm_missing" ]; then
	echo "It seems that we do not have the necessary write permissions"
	echo "Perhaps try running this script as a privileged user:"
	echo ""
	echo "    sudo $0"
fi

exit 1
