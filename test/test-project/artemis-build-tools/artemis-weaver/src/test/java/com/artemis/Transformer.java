package com.artemis;

import static org.junit.Assert.assertEquals;

import java.io.InputStream;

import com.artemis.weaver.OptimizationTransmuter;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;

import com.artemis.meta.ClassMetadata;
import com.artemis.meta.ClassMetadata.OptimizationType;
import com.artemis.meta.ClassMetadata.WeaverType;
import com.artemis.weaver.ComponentTypeTransmuter;

final class Transformer {
	
	private Transformer() {}
	
	static ClassReader transform(Class<?> klazz) throws Exception {
		InputStream classStream = klazz.getResourceAsStream("/" + klazz.getName().replace('.', '/') + ".class");
		ClassReader cr = Weaver.classReaderFor(classStream);
		ClassMetadata meta = Weaver.scan(cr);

		ClassWriter cw = null;
		if (meta.annotation != WeaverType.NONE) {
			ComponentTypeTransmuter weaver = new ComponentTypeTransmuter(null, cr, meta);
			weaver.call();
			cw = weaver.getClassWriter();
		} else if (meta.sysetemOptimizable != OptimizationType.NOT_OPTIMIZABLE) {
			OptimizationTransmuter weaver = new OptimizationTransmuter(null, cr, meta);
			weaver.call();
			cw = weaver.getClassWriter();
		}
		
		assertEquals("", ClassUtil.verifyClass(cw));
		
		classStream.close();
		
		return new ClassReader(cw.toByteArray());
	}
}

