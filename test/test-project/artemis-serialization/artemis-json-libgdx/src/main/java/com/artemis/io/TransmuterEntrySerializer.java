package com.artemis.io;

import com.artemis.Component;
import com.artemis.utils.Bag;
import com.badlogic.gdx.utils.Json;
import com.badlogic.gdx.utils.JsonValue;

public class TransmuterEntrySerializer implements Json.Serializer<ArchetypeMapper.TransmuterEntry> {
	SaveFileFormat.ComponentIdentifiers identifiers;

	@Override
	public void write(Json json, ArchetypeMapper.TransmuterEntry object, Class knownType) {
		json.writeArrayStart();
		for (int i = 0; i < object.componentTypes.size(); i++) {
			Class<? extends Component> type = object.componentTypes.get(i);
			String name = identifiers.typeToName.get(type);
			json.writeValue(name);
		}

		json.writeArrayEnd();
	}

	@Override
	public ArchetypeMapper.TransmuterEntry read(Json json, JsonValue jsonData, Class type) {
		Bag components = new Bag();
		for (JsonValue child = jsonData.child; child != null; child = child.next)
			components.add(identifiers.getType(json.readValue(String.class, child)));

		return new ArchetypeMapper.TransmuterEntry(components);
	}
}
