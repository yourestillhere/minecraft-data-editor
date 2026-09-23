import gzip
import os
import struct
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP_TITLE = "Minecraft Java Save Editor v2"
DIFFICULTIES = {"Peaceful": 0, "Easy": 1, "Normal": 2, "Hard": 3}
MODES = {"Survival": 0, "Creative": 1, "Adventure": 2, "Spectator": 3}

TAG_END, TAG_BYTE, TAG_SHORT, TAG_INT, TAG_LONG = 0, 1, 2, 3, 4
TAG_FLOAT, TAG_DOUBLE, TAG_BYTE_ARRAY, TAG_STRING = 5, 6, 7, 8
TAG_LIST, TAG_COMPOUND, TAG_INT_ARRAY, TAG_LONG_ARRAY = 9, 10, 11, 12

def read_string(f):
    n = struct.unpack(">H", f.read(2))[0]
    return f.read(n).decode("utf-8")

def write_string(f, s):
    b = s.encode("utf-8")
    f.write(struct.pack(">H", len(b)))
    f.write(b)

def read_payload(f, tag):
    if tag == TAG_BYTE: return struct.unpack(">b", f.read(1))[0]
    if tag == TAG_SHORT: return struct.unpack(">h", f.read(2))[0]
    if tag == TAG_INT: return struct.unpack(">i", f.read(4))[0]
    if tag == TAG_LONG: return struct.unpack(">q", f.read(8))[0]
    if tag == TAG_FLOAT: return struct.unpack(">f", f.read(4))[0]
    if tag == TAG_DOUBLE: return struct.unpack(">d", f.read(8))[0]
    if tag == TAG_BYTE_ARRAY:
        n = struct.unpack(">i", f.read(4))[0]; return f.read(n)
    if tag == TAG_STRING: return read_string(f)
    if tag == TAG_LIST:
        subtype = struct.unpack(">B", f.read(1))[0]
        n = struct.unpack(">i", f.read(4))[0]
        return subtype, [read_payload(f, subtype) for _ in range(n)]
    if tag == TAG_COMPOUND:
        d = {}
        while True:
            t = struct.unpack(">B", f.read(1))[0]
            if t == TAG_END: break
            name = read_string(f)
            d[name] = (t, read_payload(f, t))
        return d
    if tag == TAG_INT_ARRAY:
        n = struct.unpack(">i", f.read(4))[0]
        return [struct.unpack(">i", f.read(4))[0] for _ in range(n)]
    if tag == TAG_LONG_ARRAY:
        n = struct.unpack(">i", f.read(4))[0]
        return [struct.unpack(">q", f.read(8))[0] for _ in range(n)]
    raise ValueError(f"Unsupported NBT tag: {tag}")

def read_nbt(path):
    with gzip.open(path, "rb") as f:
        if struct.unpack(">B", f.read(1))[0] != TAG_COMPOUND:
            raise ValueError("NBT root is not a Compound.")
        name = read_string(f)
        return name, read_payload(f, TAG_COMPOUND)

def write_payload(f, tag, value):
    if tag == TAG_BYTE: f.write(struct.pack(">b", int(value)))
    elif tag == TAG_SHORT: f.write(struct.pack(">h", int(value)))
    elif tag == TAG_INT: f.write(struct.pack(">i", int(value)))
    elif tag == TAG_LONG: f.write(struct.pack(">q", int(value)))
    elif tag == TAG_FLOAT: f.write(struct.pack(">f", float(value)))
    elif tag == TAG_DOUBLE: f.write(struct.pack(">d", float(value)))
    elif tag == TAG_BYTE_ARRAY:
        f.write(struct.pack(">i", len(value))); f.write(value)
    elif tag == TAG_STRING: write_string(f, value)
    elif tag == TAG_LIST:
        subtype, values = value
        f.write(bytes([subtype])); f.write(struct.pack(">i", len(values)))
        for v in values: write_payload(f, subtype, v)
    elif tag == TAG_COMPOUND:
        for name, (t, v) in value.items():
            f.write(bytes([t])); write_string(f, name); write_payload(f, t, v)
        f.write(b"\x00")
    elif tag == TAG_INT_ARRAY:
        f.write(struct.pack(">i", len(value)))
        for v in value: f.write(struct.pack(">i", int(v)))
    elif tag == TAG_LONG_ARRAY:
        f.write(struct.pack(">i", len(value)))
        for v in value: f.write(struct.pack(">q", int(v)))
    else: raise ValueError(f"Unsupported NBT tag: {tag}")

def write_nbt(path, name, root):
    with gzip.open(path, "wb") as f:
        f.write(bytes([TAG_COMPOUND])); write_string(f, name)
        write_payload(f, TAG_COMPOUND, root)

def backup(path):
    b = path + ".backup"
    i = 1
    while os.path.exists(b): b = path + f".backup{i}"; i += 1
    with open(path, "rb") as a, open(b, "wb") as c: c.write(a.read())
    return b

def compound(root, *keys):
    cur = root
    for key in keys:
        if key not in cur or cur[key][0] != TAG_COMPOUND: return None
        cur = cur[key][1]
    return cur

def first_player_dat(world):
    p = os.path.join(world, "playerdata")
    if not os.path.isdir(p): return None
    files = [x for x in os.listdir(p) if x.endswith(".dat") and not x.endswith(".dat_old")]
    return os.path.join(p, files[0]) if files else None

def xp_for_level(level):
    if level <= 16: return level * level + 6 * level
    if level <= 31: return int(2.5 * level * level - 40.5 * level + 360)
    return int(4.5 * level * level - 162.5 * level + 2220)

def get(root, key, default=None):
    return root.get(key, (None, default))[1]

class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("820x720")
        self.root.minsize(760, 650)

        self.world = tk.StringVar()
        self.auto = tk.BooleanVar(value=True)
        self.interval = tk.IntVar(value=2)
        self.status = tk.StringVar(value="Select a world folder.")
        self.level = tk.StringVar(value="300")
        self.progress = tk.StringVar(value="0.0")
        self.mode = tk.StringVar(value="Survival")
        self.difficulty = tk.StringVar(value="Peaceful")
        self.locked = tk.BooleanVar(value=False)
        self.health = tk.StringVar(value="20")
        self.food = tk.StringVar(value="20")
        self.x = tk.StringVar(value="0")
        self.y = tk.StringVar(value="64")
        self.z = tk.StringVar(value="0")
        self.time = tk.StringVar(value="0")
        self.weather = tk.StringVar(value="Clear")
        self.keep = tk.BooleanVar(value=False)
        self.running = True
        self.last_snapshot = None

        style = ttk.Style()
        try: style.theme_use("vista")
        except tk.TclError: pass

        main = ttk.Frame(root, padding=16); main.pack(fill="both", expand=True)
        ttk.Label(main, text=APP_TITLE, font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(main, text="Offline single-player world editor • auto-refresh reads the save periodically",
                  foreground="#666").pack(anchor="w", pady=(0, 12))

        wf = ttk.LabelFrame(main, text="World", padding=10); wf.pack(fill="x")
        ttk.Entry(wf, textvariable=self.world).pack(side="left", fill="x", expand=True)
        ttk.Button(wf, text="Browse...", command=self.browse).pack(side="left", padx=8)
        ttk.Checkbutton(wf, text="Auto-refresh", variable=self.auto).pack(side="left")
        ttk.Label(wf, text="Every").pack(side="left", padx=(10, 3))
        ttk.Spinbox(wf, from_=1, to=60, textvariable=self.interval, width=4).pack(side="left")
        ttk.Label(wf, text="s").pack(side="left", padx=(3, 0))

        nb = ttk.Notebook(main); nb.pack(fill="both", expand=True, pady=12)

        xpframe = ttk.Frame(nb, padding=12); nb.add(xpframe, text="XP / Player")
        self.row(xpframe, "XP Level", self.level, 0)
        self.row(xpframe, "Progress (0–1)", self.progress, 1)
        ttk.Button(xpframe, text="Apply XP", command=self.apply_xp).grid(row=2, column=1, sticky="e", pady=8)

        self.row(xpframe, "Health (0–20)", self.health, 3)
        self.row(xpframe, "Food (0–20)", self.food, 4)
        ttk.Button(xpframe, text="Apply Health / Hunger", command=self.apply_health_food).grid(row=5, column=1, sticky="e", pady=8)

        ttk.Label(xpframe, text="Game mode").grid(row=6, column=0, sticky="w", pady=5)
        ttk.Combobox(xpframe, textvariable=self.mode, values=list(MODES), state="readonly", width=22).grid(row=6, column=1, sticky="w")
        ttk.Button(xpframe, text="Apply Game Mode", command=self.apply_mode).grid(row=7, column=1, sticky="e", pady=8)

        worldf = ttk.Frame(nb, padding=12); nb.add(worldf, text="World")
        for i, (label, var) in enumerate([("X",self.x),("Y",self.y),("Z",self.z)]):
            self.row(worldf, label, var, i)
        self.row(worldf, "Time (ticks)", self.time, 3)
        ttk.Label(worldf, text="Weather").grid(row=4, column=0, sticky="w", pady=5)
        ttk.Combobox(worldf, textvariable=self.weather, values=["Clear","Rain","Thunder"], state="readonly", width=22).grid(row=4, column=1, sticky="w")
        ttk.Checkbutton(worldf, text="Keep Inventory", variable=self.keep).grid(row=5, column=1, sticky="w", pady=5)
        ttk.Button(worldf, text="Apply Coordinates / Time / Weather / Keep Inventory",
                   command=self.apply_world).grid(row=6, column=1, sticky="e", pady=12)

        diff = ttk.Frame(nb, padding=12); nb.add(diff, text="Difficulty")
        ttk.Label(diff, text="Difficulty").grid(row=0,column=0,sticky="w",pady=5)
        ttk.Combobox(diff,textvariable=self.difficulty,values=list(DIFFICULTIES),state="readonly",width=22).grid(row=0,column=1,sticky="w")
        ttk.Checkbutton(diff,text="Lock difficulty",variable=self.locked).grid(row=1,column=1,sticky="w",pady=5)
        ttk.Button(diff,text="Apply Difficulty",command=self.apply_difficulty).grid(row=2,column=1,sticky="e",pady=12)

        bottom = ttk.Frame(main); bottom.pack(fill="x")
        ttk.Label(bottom, textvariable=self.status, wraplength=700).pack(side="left", fill="x", expand=True)
        ttk.Button(bottom, text="Refresh Now", command=self.refresh).pack(side="right")

        ttk.Label(main, text="Close Minecraft before applying changes. Backups are created automatically.",
                  foreground="#8a5a00").pack(anchor="w", pady=(8,0))

        self.root.after(1000, self.tick)

    def row(self, parent, label, var, r):
        ttk.Label(parent,text=label).grid(row=r,column=0,sticky="w",pady=5)
        ttk.Entry(parent,textvariable=var,width=24).grid(row=r,column=1,sticky="w")

    def browse(self):
        p = filedialog.askdirectory(title="Select Minecraft world folder")
        if p:
            self.world.set(p); self.refresh()

    def paths(self):
        w = self.world.get().strip()
        if not os.path.isdir(w): raise ValueError("Select a valid world folder.")
        pp = first_player_dat(w)
        if not pp: raise ValueError("No playerdata/*.dat file found. Enter the world once first.")
        lp = os.path.join(w, "level.dat")
        if not os.path.isfile(lp): raise ValueError("level.dat not found.")
        return w, pp, lp

    def refresh(self):
        try:
            w, pp, lp = self.paths()
            _, p = read_nbt(pp)
            _, l = read_nbt(lp)
            d = compound(l, "Data") or {}
            self.level.set(str(get(p,"XpLevel",0)))
            self.progress.set(str(get(p,"XpP",0.0)))
            self.health.set(str(get(p,"Health",20.0)))
            self.food.set(str(get(p,"foodLevel",20)))
            pos = get(p,"Pos",None)
            if pos and pos[0] == TAG_DOUBLE:
                vals = pos[1]
                if len(vals) >= 3:
                    self.x.set(f"{vals[0]:.3f}"); self.y.set(f"{vals[1]:.3f}"); self.z.set(f"{vals[2]:.3f}")
            self.time.set(str(get(d,"Time",0)))
            dif = int(get(d,"Difficulty",2))
            self.difficulty.set(next((k for k,v in DIFFICULTIES.items() if v==dif),"Normal"))
            self.locked.set(bool(get(d,"DifficultyLocked",0)))
            self.keep.set(bool(get(d,"GameRules",{}).get("keepInventory",(TAG_BYTE,0))[1]) if isinstance(get(d,"GameRules",{}),dict) else False)
            gm = int(get(p,"playerGameType",0))
            self.mode.set(next((k for k,v in MODES.items() if v==gm),"Survival"))
            if get(d,"raining",False): self.weather.set("Rain" if not get(d,"thundering",False) else "Thunder")
            else: self.weather.set("Clear")
            self.status.set("Refreshed from save.")
        except Exception as e:
            self.status.set(str(e))

    def save_player(self, edit):
        w, pp, _ = self.paths()
        bak = backup(pp)
        name, root = read_nbt(pp); edit(root); write_nbt(pp,name,root)
        return bak

    def save_level(self, edit):
        w, _, lp = self.paths()
        bak = backup(lp)
        name, root = read_nbt(lp); edit(root); write_nbt(lp,name,root)
        return bak

    def apply_xp(self):
        try:
            lv=int(self.level.get()); prog=float(self.progress.get())
            if lv<0 or not 0<=prog<=1: raise ValueError("Level must be >= 0 and progress must be 0–1.")
            total=xp_for_level(lv)
            bak=self.save_player(lambda r: (r.__setitem__("XpLevel",(TAG_INT,lv)),
                                            r.__setitem__("XpP",(TAG_FLOAT,prog)),
                                            r.__setitem__("XpTotal",(TAG_INT,total))))
            self.status.set(f"XP set to level {lv} ({total:,} total XP). Backup: {os.path.basename(bak)}")
        except Exception as e: messagebox.showerror("XP",str(e))

    def apply_health_food(self):
        try:
            h=float(self.health.get()); food=int(self.food.get())
            if not 0<=h<=20 or not 0<=food<=20: raise ValueError("Health must be 0–20 and food must be 0–20.")
            bak=self.save_player(lambda r: (r.__setitem__("Health",(TAG_FLOAT,h)),r.__setitem__("foodLevel",(TAG_INT,food))))
            self.status.set(f"Health {h}, food {food}. Backup: {os.path.basename(bak)}")
        except Exception as e: messagebox.showerror("Health / Food",str(e))

    def apply_mode(self):
        try:
            mode=MODES[self.mode.get()]
            bak=self.save_player(lambda r: r.__setitem__("playerGameType",(TAG_INT,mode)))
            self.status.set(f"Game mode set to {self.mode.get()}. Backup: {os.path.basename(bak)}")
        except Exception as e: messagebox.showerror("Game mode",str(e))

    def apply_world(self):
        try:
            x,y,z=map(float,(self.x.get(),self.y.get(),self.z.get()))
            t=int(self.time.get()) % 24000
            weather=self.weather.get(); keep=self.keep.get()
            def edit(r):
                r["Pos"]=(TAG_LIST,(TAG_DOUBLE,[x,y,z]))
                r["Rotation"] = r.get("Rotation",(TAG_LIST,(TAG_FLOAT,[0.0,0.0])))
                d=compound(r)  # unused
            self.save_player(lambda r: r.__setitem__("Pos",(TAG_LIST,(TAG_DOUBLE,[x,y,z]))))
            def level_edit(root):
                d=compound(root,"Data")
                d["Time"]=(TAG_LONG,t)
                d["raining"]=(TAG_BYTE,1 if weather!="Clear" else 0)
                d["thundering"]=(TAG_BYTE,1 if weather=="Thunder" else 0)
                d["rainTime"]=(TAG_INT,6000 if weather=="Rain" else 0)
                d["thunderTime"]=(TAG_INT,6000 if weather=="Thunder" else 0)
                rules=d.get("GameRules")
                if rules and rules[0]==TAG_COMPOUND:
                    rules[1]["keepInventory"]=(TAG_STRING,"true" if keep else "false")
            self.save_level(level_edit)
            self.status.set("Coordinates, time, weather and keep-inventory applied.")
        except Exception as e: messagebox.showerror("World settings",str(e))

    def apply_difficulty(self):
        try:
            def edit(root):
                d=compound(root,"Data")
                d["Difficulty"]=(TAG_BYTE,DIFFICULTIES[self.difficulty.get()])
                d["DifficultyLocked"]=(TAG_BYTE,1 if self.locked.get() else 0)
            bak=self.save_level(edit)
            self.status.set(f"Difficulty: {self.difficulty.get()}. Backup: {os.path.basename(bak)}")
        except Exception as e: messagebox.showerror("Difficulty",str(e))

    def tick(self):
        if self.auto.get():
            self.refresh()
        self.root.after(max(1,self.interval.get())*1000,self.tick)

if __name__ == "__main__":
    root=tk.Tk()
    App(root)
    root.mainloop()
