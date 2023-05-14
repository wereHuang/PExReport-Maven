package com.artemis;

import com.artemis.utils.BitVector;

/**
 * Builder for {@link EntityTransmuter}.
 * @see EntityEdit for a list of alternate ways to alter composition and access components.
 */
public final class EntityTransmuterFactory {
	private final ComponentTypeFactory types;
	private final BitVector additions;
	private final BitVector removals;
	private final World world;

	/** Prepare new builder. */
	public EntityTransmuterFactory(World world) {
		this.world = world;
		types = world.getComponentManager().typeFactory;
		additions = new BitVector();
		removals = new BitVector();
	}

	/** Component to add upon transmutation. Overwrites and retires if component exists! */
	public EntityTransmuterFactory add(Class<? extends Component> component) {
		int index = types.getIndexFor(component);
		additions.set(index, true);
		removals.set(index, false);
		return this;
	}

	/** Component to remove upon transmutation. Does nothing if missing. */
	public EntityTransmuterFactory remove(Class<? extends Component> component) {
		int index = types.getIndexFor(component);
		additions.set(index, false);
		removals.set(index, true);
		return this;
	}

	/** Build instance */
	public EntityTransmuter build() {
		return new EntityTransmuter(world, additions, removals);
	}
}
