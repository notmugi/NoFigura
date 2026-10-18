package org.figuramc.figura.compat;

import com.mojang.blaze3d.vertex.PoseStack;
import com.mojang.math.Axis;
import org.figuramc.figura.FiguraMod;
import org.joml.Vector3f;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;

/** Optional PAL bridge: Figura's pivot submission bypasses PAL's held-item mixin. */
public final class PlayerAnimationCompat {
    private static Class<?> stateType;
    private static Constructor<?> boneConstructor;
    private static Method getManager, isActive, getTransform;
    private static Field position, rotation, scale;
    private static boolean available;

    static {
        try {
            stateType = Class.forName("com.zigythebird.playeranim.accessors.IAvatarAnimationState");
            Class<?> bone = Class.forName("com.zigythebird.playeranimcore.bones.PlayerAnimBone");
            getManager = stateType.getMethod("playerAnimLib$getAnimManager");
            Class<?> manager = getManager.getReturnType();
            isActive = manager.getMethod("isActive");
            getTransform = manager.getMethod("get3DTransform", bone);
            boneConstructor = bone.getConstructor(String.class);
            position = bone.getField("position");
            rotation = bone.getField("rotation");
            scale = bone.getField("scale");
            available = true;
        } catch (ClassNotFoundException ignored) {
            // PAL is optional; do not add a runtime dependency for other avatars.
        } catch (ReflectiveOperationException | LinkageError e) {
            FiguraMod.LOGGER.warn("Player Animation Library held-item compatibility unavailable", e);
        }
    }

    private static final class EntityAccess {
        static Class<?> type;
        static Method manager;
        static {
            try {
                type = Class.forName("com.zigythebird.playeranim.accessors.IAnimatedAvatar");
                manager = type.getMethod("playerAnimLib$getAnimManager");
            } catch (ReflectiveOperationException | LinkageError ignored) {
                type = null;
            }
        }
    }

    public static boolean isAnimatingEntity(Object entity) {
        if (!available || EntityAccess.type == null || !EntityAccess.type.isInstance(entity))
            return false;
        try {
            Object manager = EntityAccess.manager.invoke(entity);
            return manager != null && Boolean.TRUE.equals(isActive.invoke(manager));
        } catch (ReflectiveOperationException | RuntimeException | LinkageError e) {
            EntityAccess.type = null;
            FiguraMod.LOGGER.warn("Disabling PAL entity animation detection after an error", e);
            return false;
        }
    }

    private static final class CombatAccess {
        static Method layer, active;
        static Object attack;
        static {
            try {
                Class<?> access = Class.forName("com.zigythebird.playeranim.api.PlayerAnimationAccess");
                layer = access.getMethod("getPlayerAnimationLayer", net.minecraft.world.entity.Avatar.class,
                        net.minecraft.resources.Identifier.class);
                active = Class.forName("com.zigythebird.playeranimcore.animation.layered.IAnimation").getMethod("isActive");
                attack = net.minecraft.resources.Identifier.fromNamespaceAndPath("bettercombat", "attack");
            } catch (ReflectiveOperationException | LinkageError ignored) {
                layer = null;
            }
        }
    }

    public static boolean isAttackingEntity(Object entity) {
        if (!(entity instanceof net.minecraft.world.entity.Avatar) || CombatAccess.layer == null)
            return false;
        try {
            Object attack = CombatAccess.layer.invoke(null, entity, CombatAccess.attack);
            return attack != null && Boolean.TRUE.equals(CombatAccess.active.invoke(attack));
        } catch (ReflectiveOperationException | RuntimeException | LinkageError e) {
            CombatAccess.layer = null;
            FiguraMod.LOGGER.warn("Disabling Better Combat pose detection after an error", e);
            return false;
        }
    }

    private static final class FirstPersonAccess {
        static Method pass;
        static {
            try {
                if (stateType != null) pass = stateType.getMethod("playerAnimLib$isFirstPersonPass");
            } catch (ReflectiveOperationException ignored) {}
        }
    }

    public static boolean isFirstPersonPass(Object state) {
        if (stateType == null || !stateType.isInstance(state) || FirstPersonAccess.pass == null)
            return false;
        try {
            return Boolean.TRUE.equals(FirstPersonAccess.pass.invoke(state));
        } catch (ReflectiveOperationException | RuntimeException | LinkageError e) {
            FirstPersonAccess.pass = null;
            FiguraMod.LOGGER.warn("Disabling PAL first-person detection after an error", e);
            return false;
        }
    }

    public static void applyItemTransform(Object state, boolean left, PoseStack stack) {
        if (!available || !stateType.isInstance(state))
            return;
        try {
            Object manager = getManager.invoke(state);
            if (manager == null || !Boolean.TRUE.equals(isActive.invoke(manager)))
                return;
            Object bone = boneConstructor.newInstance(left ? "left_item" : "right_item");
            getTransform.invoke(manager, bone);
            Vector3f pos = (Vector3f) position.get(bone);
            Vector3f rot = (Vector3f) rotation.get(bone);
            Vector3f size = (Vector3f) scale.get(bone);
            apply(stack, pos, rot, size);
        } catch (ReflectiveOperationException | RuntimeException | LinkageError e) {
            available = false;
            FiguraMod.LOGGER.warn("Disabling Player Animation Library held-item compatibility after an error", e);
        }
    }

    static void apply(PoseStack stack, Vector3f pos, Vector3f rot, Vector3f size) {
        // PAL translates in hand space before vanilla's Rx(-90)*Ry(180).
        // Figura already supplied the item-space pivot: conjugate that translation
        // into item space instead of applying the vanilla hand/arm transforms twice.
        stack.translate(-pos.x / 16f, -pos.z / 16f, pos.y / 16f);
        // Match PAL 1.2.5's item-axis mapping and conditional rotations exactly.
        if (rot.z != 0) stack.mulPose(Axis.ZP.rotation(-rot.y));
        if (rot.y != 0) stack.mulPose(Axis.YP.rotation(-rot.z));
        if (rot.x != 0) stack.mulPose(Axis.XP.rotation(-rot.x));
        stack.scale(size.x, size.y, size.z);
    }
}
