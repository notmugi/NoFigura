package org.figuramc.figura.compat;

import net.minecraft.client.Minecraft;
import org.figuramc.figura.FiguraMod;
import org.figuramc.figura.avatar.Avatar;
import org.figuramc.figura.avatar.AvatarManager;

import java.util.function.Function;

/** Let EMF select its vanilla variant before posing, rather than undoing its pose later. */
public final class EmfCompat {
    private static boolean initialized;

    public static void init() {
        if (initialized)
            return;
        initialized = true;
        try {
            Class<?> api = Class.forName("traben.entity_model_features.EMFAnimationApi");
            Function<Object, Boolean> condition = EmfCompat::useVanillaModel;
            var vanilla = api.getMethod("registerVanillaModelCondition", Function.class);
            var pause = api.getMethod("registerPauseCondition", Function.class);
            vanilla.invoke(null, condition);
            // A newly loaded EMF root may not be registered for variant selection yet.
            // Also stop its first-frame animation until the vanilla variant is selected.
            pause.invoke(null, (Function<Object, Boolean>) EmfCompat::pauseAnimations);
        } catch (ClassNotFoundException ignored) {
            // Optional: no EMF means no resource-pack player model to exclude.
        } catch (ReflectiveOperationException | LinkageError e) {
            FiguraMod.LOGGER.warn("EMF player-pose isolation unavailable", e);
        }
    }

    static boolean pauseAnimations(Object entity) {
        if (useVanillaModel(entity))
            return true;
        var minecraft = Minecraft.getInstance();
        if (minecraft.level == null || minecraft.player == null || entity != minecraft.player)
            return false;
        Avatar avatar = AvatarManager.getLoadedAvatar(minecraft.player.getUUID());
        // PAL's bundled EMF pause hook references a class removed in EMF 3.3.11.
        // Use EMF's current callback API so pack posing cannot overwrite active combat posing.
        return avatar != null && avatar.isHost && avatar.loaded && avatar.renderer != null
                && PlayerAnimationCompat.isAnimatingEntity(entity);
    }

    static boolean useVanillaModel(Object entity) {
        var minecraft = Minecraft.getInstance();
        if (minecraft.level == null || minecraft.player == null || entity != minecraft.player)
            return false;
        // Read-only lookup: don't fetch avatars or alter EMF's global lock/config state.
        Avatar avatar = AvatarManager.getLoadedAvatar(minecraft.player.getUUID());
        return avatar != null && avatar.isHost && avatar.loaded && avatar.renderer != null
                && !avatar.followsVanillaPose();
    }
}
