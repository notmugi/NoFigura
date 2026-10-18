#!/usr/bin/env python3
"""Run with python3 tests/check_compat.py; requires JDK 25, no game or dependencies."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "common/src/main/java"
JDK = Path(os.environ.get("JAVA25_HOME", "/usr/lib/jvm/java-25-openjdk")) / "bin"


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)


def main():
    run(JDK / "javac", "-version")
    run(JDK / "java", "-version")
    avatar = (SOURCE / "org/figuramc/figura/avatar/Avatar.java").read_text()
    snippets = re.findall(r"^            loaded = true;\n((?:(?!loaded = true;).)*?)\n        \}\);", avatar, re.S | re.M)
    assert len(snippets) == 1 and "allChanged()" in snippets[0], "Reload block moved; update extraction"
    work = ROOT / "tests/.work"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="compat-", dir=work) as directory:
        tmp = Path(directory)

        def java(name, text):
            path = tmp / (name + ".java")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            return path

        config = java("net/raphimc/immediatelyfast/feature/core/ImmediatelyFastConfig", """
package net.raphimc.immediatelyfast.feature.core;
public class ImmediatelyFastConfig {
    // User configuration stays enabled even when runtime resizing is disabled.
    public boolean getBoolean(String key, boolean fallback) {
        if (!key.equals("font_atlas_resizing")) throw new AssertionError(key);
        return true;
    }
    public int getInt(String key, int fallback) {
        if (!key.equals("font_atlas_size") || fallback != 2048) throw new AssertionError(key);
        return Integer.getInteger("atlas", fallback);
    }
}
""")
        runtime = java("net/raphimc/immediatelyfast/feature/core/ImmediatelyFastRuntimeConfig", """
package net.raphimc.immediatelyfast.feature.core;
public class ImmediatelyFastRuntimeConfig {
    public boolean getBoolean(String key, boolean fallback) {
        if (!key.equals("font_atlas_resizing") || fallback) throw new AssertionError(key);
        return Boolean.getBoolean("runtime");
    }
}
""")
        immediately_fast = java("net/raphimc/immediatelyfast/ImmediatelyFast", """
package net.raphimc.immediatelyfast;
import net.raphimc.immediatelyfast.feature.core.*;
public class ImmediatelyFast {
    public static final ImmediatelyFastConfig config = new ImmediatelyFastConfig();
    public static final ImmediatelyFastRuntimeConfig runtimeConfig = new ImmediatelyFastRuntimeConfig();
}
""")
        platform = java("org/figuramc/figura/utils/PlatformUtils", """
package org.figuramc.figura.utils;
public class PlatformUtils {
    public static boolean isModLoaded(String name) {
        if (!name.equals("immediatelyfast")) throw new AssertionError(name);
        return Boolean.getBoolean("present");
    }
    public static String getModVersion(String name) { return "1.14.1"; }
    public static int compareVersionTo(String version, String minimum) {
        if (!version.equals("1.14.1") || !minimum.equals("1.2.0")) throw new AssertionError(minimum);
        return 1; // This check targets the modern IF API, not legacy versions.
    }
}
""")
        font_check = java("FontCheck", """
import org.figuramc.figura.compat.ImmediatelyFastCompat;
public class FontCheck {
    public static void main(String[] args) throws Exception {
        if (!Boolean.getBoolean("present")) {
            try {
                Class.forName("net.raphimc.immediatelyfast.ImmediatelyFast");
                throw new AssertionError("IF must actually be absent from classpath");
            } catch (ClassNotFoundException expected) {}
        }
        float actual = ImmediatelyFastCompat.getFontWidthIMF();
        if (actual != Float.parseFloat(args[0])) throw new AssertionError("font width: " + actual);
    }
}
""")
        reload_check = java("ReloadCheck", """
import java.util.ArrayDeque;
public class ReloadCheck {
    static final Thread MAIN = Thread.currentThread();
    static Throwable workerFailure;
    static class Minecraft {
        static final Minecraft INSTANCE = new Minecraft();
        Object level = new Object();
        final ArrayDeque<Runnable> queue = new ArrayDeque<>();
        final Extractor levelExtractor = new Extractor();
        static Minecraft getInstance() { return INSTANCE; }
        void execute(Runnable task) { queue.add(task); }
        void drain() { while (!queue.isEmpty()) queue.remove().run(); }
    }
    static class Extractor {
        int reloads;
        void allChanged() {
            require(Thread.currentThread() == MAIN, "reload ran on worker");
            reloads++;
        }
    }
    static void require(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
    static void reload() {
""" + snippets[0] + """
    }
    static void enqueue() throws Exception {
        Minecraft mc = Minecraft.INSTANCE;
        int before = mc.levelExtractor.reloads;
        Thread worker = new Thread(ReloadCheck::reload);
        worker.setUncaughtExceptionHandler((thread, error) -> workerFailure = error);
        worker.start();
        worker.join();
        if (workerFailure != null) throw new AssertionError("worker failed", workerFailure);
        require(mc.levelExtractor.reloads == before, "inline worker reload");
        require(mc.queue.size() == 1, "expected exactly one queued reload");
    }
    public static void main(String[] args) throws Exception {
        Minecraft mc = Minecraft.INSTANCE;
        enqueue();
        mc.drain();
        require(mc.levelExtractor.reloads == 1, "missing or duplicate main-thread reload");
        enqueue();
        mc.level = null;
        mc.drain();
        require(mc.levelExtractor.reloads == 1, "reload after disconnect");
        enqueue();
        mc.level = new Object();
        mc.drain();
        require(mc.levelExtractor.reloads == 2, "level must be checked at execution time");
    }
}
""")
        stub_classes, classes = tmp / "if-classes", tmp / "classes"
        run(JDK / "javac", "--release", "25", "-d", stub_classes, config, runtime, immediately_fast)
        run(JDK / "javac", "--release", "25", "-cp", stub_classes, "-d", classes,
            platform, SOURCE / "org/figuramc/figura/compat/ImmediatelyFastCompat.java",
            font_check, reload_check)
        run(JDK / "java", "-cp", classes, "FontCheck", "256")
        for size in (1024, 2048, 4096):
            for enabled in (True, False):
                run(JDK / "java", "-cp", os.pathsep.join(map(str, (classes, stub_classes))),
                    "-Dpresent=true", f"-Datlas={size}", f"-Druntime={str(enabled).lower()}",
                    "FontCheck", size if enabled else 256)
        run(JDK / "java", "-cp", classes, "ReloadCheck")
    print("PASS: IF absent; atlases 1024/2048/4096; runtime disabled/config enabled; "
          "extracted Avatar reload queued once, main-thread only, execution-time level guard")


if __name__ == "__main__":
    main()
