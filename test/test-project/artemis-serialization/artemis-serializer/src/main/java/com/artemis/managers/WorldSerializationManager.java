package com.artemis.managers;

import com.artemis.BaseSystem;
import com.artemis.World;
import com.artemis.io.InputStreamHelper;
import com.artemis.io.SaveFileFormat;
import com.artemis.io.SerializationException;
import com.artemis.utils.IntBag;

import java.io.*;

public class WorldSerializationManager extends BaseSystem {
	private ArtemisSerializer<?> backend;
	public boolean alwaysLoadStreamMemory = true;

	// both fields re-used by load()
	private byte[] bytes;
	private ByteArrayOutputStream baos;


	@Override
	protected void processSystem() {
	}

	/**
	 * Provide a serializer that can read or write data in your choice of format (likely
	 * some form of data file, e.g. JSON).
	 */
	public void setSerializer(ArtemisSerializer<?> backend) {
		this.backend = backend;
	}

	public <T extends ArtemisSerializer> T getSerializer() {
		return (T) backend;
	}

	/**
	 * Loads data from an InputStream (usually a file) and provides a SaveFileFormat (or subclass)
	 * object that contains the deserialized data.
	 */
	public <T extends SaveFileFormat> T load(InputStream is, Class<T> format) {
		if (alwaysLoadStreamMemory || !InputStreamHelper.isMarkSupported(is)) {
			try {
				byte[] buf = byteBuffer();
				ByteArrayOutputStream baos = byteArrayOutputStream();
				int read;
				while ((read = is.read(buf)) != -1) {
					baos.write(buf, 0, read);
				}
				is = new ByteArrayInputStream(baos.toByteArray());
			} catch (IOException e) {
				throw new RuntimeException("Error copying inputstream", e);
			}
		}
		return backend.load(is, format);
	}

	/**
	 * @throws SerializationException if {@link ArtemisSerializer} was not set
	 */
	public void save(OutputStream out, SaveFileFormat format) {
		if (backend == null) {
			throw new SerializationException("Missing ArtemisSerializer, see #setSerializer.");
		}

		world.inject(format);
		backend.save(out, format);
	}

	private ByteArrayOutputStream byteArrayOutputStream() {
		if (baos == null) {
			baos = new ByteArrayOutputStream();
		} else {
			baos.reset();
		}

		return baos;
	}

	private byte[] byteBuffer() {
		if (bytes == null)
			bytes = new byte[32768];

		return bytes;
	}

	/**
	 * Override this class to actually decide the format in which an object (not necessarily
	 * of Artemis type) should be serialized.  A JSON serializer is provided, but by overriding
	 * this class you may serialize to/from YAML, XML, UDP packets, or even your own JSON format!
	 */
	public static abstract class ArtemisSerializer<T> {
		protected World world;

		protected ArtemisSerializer(World world) {
			this.world = world;
		}

		/**
		 * Convenience method for immediately serializing a group of entities with the default
		 * SaveFileFormat.  For finer control or SaveFileFormat subclasses, use #save.
		 */
		protected final void save(OutputStream out, IntBag entities) {
			save(out, new SaveFileFormat(entities));
		}

		/**
		 * Register a custom serializer for some known class.  It is left to the implementation
		 * to decide how this custom serializer is actually used.
		 */
		public abstract ArtemisSerializer register(Class<?> type, T serializer);

		protected abstract void save(OutputStream out, SaveFileFormat format);
		
		/**
		 * Deserializes data (usually a file) of a known class to a SaveFileFormat.
		 */
		protected abstract <T extends SaveFileFormat> T load(InputStream is, Class<T> format);
	}
}
