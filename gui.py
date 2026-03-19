import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
import os
from gofile_core import Manager, Downloader
import queue
import time

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class DownloadItem(ctk.CTkFrame):
    def __init__(self, master, filename, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        
        self.filename_label = ctk.CTkLabel(self, text=filename, font=ctk.CTkFont(size=13, weight="bold"))
        self.filename_label.grid(row=0, column=0, padx=10, pady=(5, 0), sticky="w")
        
        self.stats_label = ctk.CTkLabel(self, text="Waiting...", font=ctk.CTkFont(size=11))
        self.stats_label.grid(row=0, column=1, padx=10, pady=(5, 0), sticky="e")
        
        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.grid(row=1, column=0, columnspan=2, padx=10, pady=(5, 10), sticky="ew")
        self.progress_bar.set(0)

    def update_progress(self, percent, current, total, rate, status):
        self.progress_bar.set(percent / 100)
        
        unit = "B/s"
        disp_rate = rate
        if disp_rate > 1024**2: disp_rate /= 1024**2; unit = "MB/s"
        elif disp_rate > 1024: disp_rate /= 1024; unit = "KB/s"
        
        def format_size(size):
            if size is None: return "Unknown"
            s = float(size)
            for u in ['B', 'KB', 'MB', 'GB']:
                if s < 1024: return f"{round(s, 2)} {u}"
                s /= 1024
            return f"{round(s, 2)} TB"

        if status == "downloading":
            self.stats_label.configure(text=f"{format_size(current)} / {format_size(total)} | {round(disp_rate, 1)} {unit}")
        elif status == "finished":
            self.stats_label.configure(text="Finished", text_color="green")
            self.progress_bar.set(1.0)
            self.progress_bar.configure(progress_color="green")
        elif status == "starting":
            self.stats_label.configure(text="Starting...")
        elif status == "skipped":
            self.stats_label.configure(text="Skipped (Already Exists)", text_color="yellow")
            self.progress_bar.set(1.0)
            self.progress_bar.configure(progress_color="yellow")

class GofileGui(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Gofile Downloader Pro")
        self.geometry("1100x850")

        self.manager = None
        self.downloader = None
        self.log_queue = queue.Queue()
        self.progress_queue = queue.Queue()
        self.file_checkboxes = {}
        self.files_info = {}
        self.download_widgets = {}
        self.save_path = os.getcwd()

        self.setup_ui()
        self.after(100, self.process_queues)

    def setup_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, rowspan=4, sticky="nsew")
        
        self.logo_label = ctk.CTkLabel(self.sidebar, text="Gofile Pro", font=ctk.CTkFont(size=26, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.workers_label = ctk.CTkLabel(self.sidebar, text="Max Concurrence:")
        self.workers_label.grid(row=1, column=0, padx=20, pady=(10, 0), sticky="w")
        self.workers_entry = ctk.CTkEntry(self.sidebar)
        self.workers_entry.insert(0, "5")
        self.workers_entry.grid(row=2, column=0, padx=20, pady=(0, 10))

        self.dir_button = ctk.CTkButton(self.sidebar, text="Change Save Folder", command=self.select_dir)
        self.dir_button.grid(row=3, column=0, padx=20, pady=10)
        
        self.save_path_label = ctk.CTkLabel(self.sidebar, text=f"Path: {self.save_path}", font=ctk.CTkFont(size=11), wraplength=180)
        self.save_path_label.grid(row=4, column=0, padx=20, pady=5, sticky="nw")

        # Main Input area
        self.input_frame = ctk.CTkFrame(self)
        self.input_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.input_frame.grid_columnconfigure(1, weight=1)

        self.url_entry = ctk.CTkEntry(self.input_frame, placeholder_text="Gofile Link (e.g. https://gofile.io/d/abc)", height=45)
        self.url_entry.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        self.pass_entry = ctk.CTkEntry(self.input_frame, placeholder_text="Content Password", show="*", height=35)
        self.pass_entry.grid(row=1, column=0, padx=10, pady=5, sticky="ew")

        self.fetch_button = ctk.CTkButton(self.input_frame, text="Fetch Files", command=self.start_fetch, height=35)
        self.fetch_button.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        # TabView
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=1, column=1, padx=20, pady=(0, 10), sticky="nsew")
        self.tab_files = self.tabview.add("Selection")
        self.tab_downloads = self.tabview.add("Downloads")

        self.file_list_frame = ctk.CTkScrollableFrame(self.tab_files)
        self.file_list_frame.pack(fill="both", expand=True)

        self.downloads_list_frame = ctk.CTkScrollableFrame(self.tab_downloads)
        self.downloads_list_frame.pack(fill="both", expand=True)

        # Control area
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=2, column=1, padx=20, pady=10, sticky="nsew")
        self.control_frame.grid_columnconfigure((0,1,2), weight=1)

        self.download_button = ctk.CTkButton(self.control_frame, text="Start Download", state="disabled", command=self.start_download, height=45)
        self.download_button.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.pause_button = ctk.CTkButton(self.control_frame, text="Pause All", state="disabled", fg_color="#FBC02D", hover_color="#F9A825", text_color="black", command=self.pause_all, height=45)
        self.pause_button.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        self.stop_button = ctk.CTkButton(self.control_frame, text="Stop & Cancel", state="disabled", fg_color="#D32F2F", hover_color="#B71C1C", command=self.stop_all, height=45)
        self.stop_button.grid(row=0, column=2, padx=10, pady=10, sticky="ew")

        self.overall_label = ctk.CTkLabel(self.control_frame, text="Total Progress:")
        self.overall_label.grid(row=1, column=0, columnspan=3, padx=20, pady=(5,0), sticky="w")
        self.overall_progress = ctk.CTkProgressBar(self.control_frame)
        self.overall_progress.grid(row=2, column=0, columnspan=3, padx=20, pady=(0, 10), sticky="ew")
        self.overall_progress.set(0)

        # Log area
        self.log_text = ctk.CTkTextbox(self, height=130, font=ctk.CTkFont(family="Consolas", size=11))
        self.log_text.grid(row=3, column=1, padx=20, pady=(0, 20), sticky="nsew")

    def select_dir(self):
        dir_path = filedialog.askdirectory()
        if dir_path:
            self.save_path = dir_path
            self.save_path_label.configure(text=f"Path: {dir_path}")

    def log(self, msg):
        self.log_queue.put(msg)

    def start_fetch(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a valid URL")
            return

        self.fetch_button.configure(state="disabled")
        self.log(f"Fetching: {url}")
        
        for widget in self.file_checkboxes.values():
            widget.destroy()
        self.file_checkboxes = {}
        self.tabview.set("Selection")

        threading.Thread(target=self.fetch_thread, args=(url, self.pass_entry.get().strip()), daemon=True).start()

    def fetch_thread(self, url, password):
        try:
            self.manager = Manager(output_callback=self.log)
            if not self.manager.login():
                self.log("Authentication failed.")
                self.after(0, lambda: self.fetch_button.configure(state="normal"))
                return

            self.downloader = self.manager.get_downloader(url, password)
            self.downloader._root_dir = self.save_path

            self.files_info = self.downloader.fetch_metadata()
            self.after(0, self.update_file_list)
        except Exception as e:
            self.log(f"Fetch Error: {str(e)}")
            self.after(0, lambda: self.fetch_button.configure(state="normal"))

    def update_file_list(self):
        self.fetch_button.configure(state="normal")
        if not self.files_info:
            self.log("No files detected.")
            return

        for k, v in self.files_info.items():
            cb = ctk.CTkCheckBox(self.file_list_frame, text=f"{v['filename']} ({v['path']})")
            cb.select()
            cb.pack(fill="x", padx=10, pady=3)
            self.file_checkboxes[k] = cb

        self.download_button.configure(state="normal")
        self.log(f"Found {len(self.files_info)} items.")

    def start_download(self):
        selected = [k for k, cb in self.file_checkboxes.items() if cb.get() == 1]
        if not selected:
            messagebox.showwarning("Warning", "Pick at least one file")
            return

        self.download_button.configure(state="disabled")
        self.pause_button.configure(state="normal")
        self.stop_button.configure(state="normal")
        self.fetch_button.configure(state="disabled")
        
        # Reset downloads tab
        for w in self.download_widgets.values():
            w.destroy()
        self.download_widgets = {}
        self.tabview.set("Downloads")

        workers = int(self.workers_entry.get() or "5")
        self.downloader._max_workers = workers
        self.downloader._progress_callback = self.progress_callback
        
        self.log(f"Downloading {len(selected)} items...")
        self.overall_progress.set(0)
        
        threading.Thread(target=self.download_thread, args=(selected,), daemon=True).start()

    def download_thread(self, selected):
        try:
            self.downloader.run(selected_indices=selected)
            self.log("Batch download process completed.")
        except Exception as e:
            self.log(f"Runtime Error: {str(e)}")
        finally:
            self.after(0, self.on_download_finish)

    def on_download_finish(self):
        self.download_button.configure(state="normal")
        self.pause_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.fetch_button.configure(state="normal")
        self.overall_progress.set(1.0)

    def progress_callback(self, data):
        self.progress_queue.put(data)

    def pause_all(self):
        if self.manager:
            self.manager.pause()
            self.log("Pause signal sent. Downloads will halt (can be resumed).")

    def stop_all(self):
        if self.manager:
            self.manager.stop()
            self.log("Stop signal sent. Discarding partial downloads.")

    def process_queues(self):
        # Logs
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
                self.log_text.see("end")
        except queue.Empty:
            pass

        # Progress
        try:
            while True:
                data = self.progress_queue.get_nowait()
                index = data['index']
                filename = data['filename']
                
                if index not in self.download_widgets:
                    widget = DownloadItem(self.downloads_list_frame, filename)
                    widget.pack(fill="x", padx=10, pady=5)
                    self.download_widgets[index] = widget
                
                self.download_widgets[index].update_progress(
                    data.get('percent', 0),
                    data.get('current', 0),
                    data.get('total', 0),
                    data.get('rate', 0),
                    data.get('status', 'unknown')
                )
                
                # Overall
                total_files = len(self.download_widgets)
                if total_files > 0:
                    total_progress = sum(w.progress_bar.get() for w in self.download_widgets.values())
                    self.overall_progress.set(total_progress / total_files)
                    
        except queue.Empty:
            pass

        self.after(50, self.process_queues)

if __name__ == "__main__":
    app = GofileGui()
    app.mainloop()
