#!/bin/bash

# Take switches as arguments
# --test: test mode, don't copy anything
# --forget: don't remember copied folders
# --quiet: don't print anything, only log to history

# Define paths


cwd=$(dirname "$0")

root_folder="/path/to/your/books"
source_folder="/path/to/your/books"
destination_folder="/path/to/your/books/#convert/inbox"
converted_folder="/path/to/your/books/#convert/converted"
log_file="$cwd/cp-to-convert.log"
history_file="$cwd/history.log"

ignored_dirs=(
    "#convert"
    "#done"
    "#books"
    "@eaDir"
    ".DS_Store"
)

# Define switches
TEST_MODE=false
FORGET_MODE=false
FORCE=false
QUIET_MODE=false

torrentpath="${@: -1}" # last argument
torrentname="${@: -2:1}" # second to last argument
torrentid="${@: -3:1}" # third to last argument
torrentfullpath="$torrentpath/$torrentname"

export TEST_MODE
export FORGET_MODE
export QUIET_MODE
export FORCE
export converted_folder
export destination_folder
export root_folder
export torrentpath
export source_folder
export log_file
export history_file

# Parse switches
for arg in "$@"; do
    case $arg in
        --test)
            TEST_MODE=true
            ;;
        --forget)
            FORGET_MODE=true
            ;;
        --quiet)
            QUIET_MODE=true
            ;;
        --force)
            FORCE=true
            ;;
        # if torrentpath is not empty and starts with /, assume this is the source folder
        */*)
            if [ -n "$torrentfullpath" ] && [ -d "$torrentfullpath" ] && [ "$torrentfullpath" != "$root_folder" ]; then
                source_folder="$torrentfullpath"
            fi
            ;;
    esac
done

# Make sure log files exist and are writeable
touch -a "$history_file"
chmod 666 "$history_file"
if [ ! -w "$history_file" ]; then
    echo "History file \"$history_file\" is not writeable."
    exit 1
fi

touch -a "$log_file"
chmod 666 "$log_file"
if [ ! -w "$log_file" ]; then
    echo "Log file \"$log_file\" is not writeable."
    exit 1
fi

# Open the log file for appending
exec 3>> "$log_file"

echolog() {
    # if last arg is "no-date", don't print date
    prnt="$@"
    logline="$(date +"%Y-%m-%d %H:%M:%S") $@"
    if [ "${@: -1}" == "no-date" ]; then
        # remove "no-date" from logline and prnt
        logline=$prnt
    fi
    # remove "no-date" from prnt and logline
    prnt=${prnt%no-date}
    logline=${logline%no-date}

    if [ "$QUIET_MODE" = false ]; then
        echo -e "$prnt"
    fi
    echo -e "$logline" >> /dev/fd/3
}
export -f echolog

now=$(date +"%Y-%m-%d %H:%M:%S")
line=$(printf "%0.s-" {1..80})
echolog "$line" no-date
echolog "$now cp-to-convert.sh $@" no-date
echolog ""

if [ "$TEST_MODE" = true ]; then
   echolog " * Test mode enabled, no files will be copied"
fi

if [ "$FORGET_MODE" = true ]; then
    echolog " * Forget mode enabled, copied folders will not be remembered"
fi

# Ensure destination folder exists
if [ ! -d "$destination_folder" ]; then
    echolog "Destination folder \"$destination_folder\" does not exist."
    exit 1
fi

# Ensure source folder exists
if [ ! -d "$source_folder" ]; then
    echolog "Source folder \"$source_folder\" does not exist."
    exit 1
fi

# Ensure root folder exists
if [ ! -d "$root_folder" ]; then
    echolog "Root folder \"$root_folder\" does not exist."
    exit 1
fi

# get number of folders in $full_path with > 0 mp3 files
mp3_folders() {
    find "$1" -mindepth 1 -maxdepth 1 -type d -exec sh -c '
        mp3_count=$(find "$0" -type f -name "*.mp3" | wc -l)
        if [ $mp3_count -gt 0 ]; then
            echo "$0"
        fi
    ' {} \; | wc -l
}
export -f mp3_folders

process_book() {
    # if [ ! -d "$0" ]; then
    #     continue
    # fi
    mp3_count=$(find "$0" -maxdepth 1 -type f -name "*.mp3" | wc -l)
    full_path=$(realpath "$0")
    folder_name=$(basename "${0%/}")
    parent_dir=$(realpath "$0/..")
    rel_child_path=./$(realpath --relative-to="$root_folder" "$0")

    # if foldername is "" or ".", skip
    if [ "$folder_name" == "" ] || [ "$folder_name" == "." ]; then
        return
    fi

    if [ $mp3_count -gt 1 ]; then
        if $(grep -w -E -q "$rel_child_path/?$" "$history_file") && [ ! "$FORCE" == true ]; then
            echolog "   ✓ $rel_child_path  :: (already copied)"    
            return
        elif [ -d "$converted_folder/$folder_name" ]; then
            echolog "   ✓ $rel_child_path :: (found in converted dir)"
            return
        elif [ "$1" == "single" ] && [ "$parent_dir" != "$root_folder" ]; then
            # if $1 == single, allow copying of second-level-deep folders *only* if the root dir contains only one file with mp3 files
            # get number of folders in $parent_dir with > 0 mp3 files
            mp3dirs=$(mp3_folders "$parent_dir")
            if [ $mp3dirs -gt 1 ]; then
                echolog "   × $folder_name - (more than one multi-part mp3 audiobook in parent dir)"
                return
            fi
        fi
        copy_msg=$([ "$FORCE" == true ] && echo "already copied, but force mode enabled" || echo "copying")
        echolog " * → $rel_child_path :: ($mp3_count mp3 files - $copy_msg)"
        if [ ! "$TEST_MODE" == true ]; then
            # if single mode, copy $full_path to $destination_folder/, e.g. "/path/to/your/books/Chuck" becomes "/path/to/your/books/#convert/inbox/Chuck"
            # if root mode, copy $full_path/$folder_name to $destination_folder/, e.g. "/path/to/your/books/Chuck" becomes "/path/to/your/books/#convert/inbox/Chuck"
            if [ "$1" == "single" ]; then
                # echo "cp -r \"$full_path\" \"$destination_folder/\""
                cp -r "$full_path" "$destination_folder/"
            else
                # echo "cp -r \"$full_path/$folder_name\" \"$destination_folder/\""
                cp -r "$full_path" "$destination_folder/"
            fi
        fi
        if [ ! "$FORGET_MODE" == true ]; then
            echo "$rel_child_path" >> "$history_file"
        fi
    elif [ "$1" == "single" ]; then
        echolog "   × $rel_child_path :: (not a multi-part mp3 audiobook)"
        return
    fi
}
export -f process_book

process_dir() {
    echolog ""
    mindepth=$([ "$1" == "single" ] && echo 0 || echo 1)
    maxdepth=$([ "$1" == "single" ] && echo 1 || echo 1)
    # ignore all folders that contain any of the ignore strings, e.g. \( ! -name '*Fight Club*' -a ! -name '*@eaDir*' \)
    
    # Populate the exclusion patterns array
    for ignored_string in "${ignored_dirs[@]}"; do
        exclude_paths+=" ! -name $ignored_string"
    done

    # echo "find \"$1\" -mindepth $mindepth -maxdepth $maxdepth -type d \( ${exclude_paths} \) -exec echo {} \;"
    # ignore all folders that contain any of the ignore strings
    find "$source_folder" -mindepth $mindepth -maxdepth $maxdepth -type d \( ${exclude_paths} \) -exec sh -c '
        process_book "$@"
    ' {} "$@" \;
}

if [ -n "$torrentpath" ] && [ -d "$torrentpath" ]; then
    echolog " * Checking \"$source_folder\""
    process_dir single
else 
    echolog " * Checking all folders in \"$source_folder\""
    process_dir root
fi

# Release the file descriptor
exec 3>&-
