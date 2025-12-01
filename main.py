# main.py
import tkinter as tk
import subprocess
from main_app import AndroidMultiControlApp

if __name__ == "__main__":
    root = tk.Tk()
    app = AndroidMultiControlApp(root)
    root.mainloop()