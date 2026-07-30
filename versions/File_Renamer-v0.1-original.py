import os
import random
import string
import tkinter as tk
from tkinter import filedialog, messagebox


def generate_random_name(length=8):
    """Generate a random alphanumeric string."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def select_files():
    """Open file dialog and allow selecting multiple files."""
    files = filedialog.askopenfilenames(title="Select Files to Rename")
    if files:
        file_list.delete(0, tk.END)
        for f in files:
            file_list.insert(tk.END, f)


def rename_files():
    """Rename all selected files using random names and chosen extension."""
    files = file_list.get(0, tk.END)
    new_ext = ext_entry.get().strip().lower()

    if not files:
        messagebox.showerror("Error", "No files selected.")
        return

    # Ensure extension begins with a dot
    if new_ext and not new_ext.startswith("."):
        new_ext = "." + new_ext

    if not new_ext:
        messagebox.showerror("Error", "Please enter a file extension.")
        return

    for file_path in files:
        folder = os.path.dirname(file_path)
        new_name = generate_random_name() + new_ext
        new_path = os.path.join(folder, new_name)

        # Avoid accidental overwrite
        while os.path.exists(new_path):
            new_name = generate_random_name() + new_ext
            new_path = os.path.join(folder, new_name)

        os.rename(file_path, new_path)

    messagebox.showinfo("Success", "All files renamed successfully!")
    file_list.delete(0, tk.END)


# ---------------- GUI SETUP ---------------- #

root = tk.Tk()
root.title("Random File Renamer")
root.geometry("500x400")

# Instruction Label
tk.Label(root, text="Select files and enter the new extension:", font=("Arial", 12)).pack(pady=10)

# File list box
file_list = tk.Listbox(root, width=70, height=12)
file_list.pack(pady=5)

# Select files button
tk.Button(root, text="Select Files", command=select_files, width=20).pack(pady=5)

# Extension field
ext_frame = tk.Frame(root)
ext_frame.pack(pady=10)

tk.Label(ext_frame, text="New extension (e.g., .txt): ").pack(side=tk.LEFT)
ext_entry = tk.Entry(ext_frame, width=10)
ext_entry.pack(side=tk.LEFT)

# Rename button
tk.Button(root, text="Rename Files", command=rename_files, width=20, bg="#4CAF50", fg="white").pack(pady=20)

root.mainloop()