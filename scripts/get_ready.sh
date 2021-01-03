#! /bin/bash
# This should be run inside kinobot/scripts folder

SCRIPTS="$(pwd)"

[[ ! $SCRIPTS == *"kinobot/scripts"* ]] && echo "Wrong folder" && exit 1 

case ":${PATH:=$SCRIPTS}:" in
    *:"$SCRIPTS":*)  ;;
    *) PATH="$SCRIPTS:$PATH"  ;;
esac

sed -i "/export PATH/c\\export PATH='$PATH'" ~/.bashrc

echo "Source ~/.bashrc to proceed"
