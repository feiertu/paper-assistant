package com.paperassistant.entity;

import com.pgvector.PGvector;
import org.hibernate.engine.spi.SharedSessionContractImplementor;
import org.hibernate.usertype.UserType;

import java.io.Serializable;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.util.Arrays;

/**
 * Hibernate {@link UserType} mapping a {@code float[]} property to the
 * pgvector {@code vector(1024)} column.
 *
 * <p>The pgvector JDBC driver (com.pgvector:pgvector) ships the {@link PGvector}
 * wrapper but no Hibernate type registration, so with {@code ddl-auto: validate}
 * Hibernate would expect the default {@code real[]} mapping for {@code float[]}
 * and fail startup against the real {@code vector} column. This type makes the
 * mapping explicit:
 *
 * <ul>
 *   <li>sql type {@link Types#OTHER} (matches how the JDBC driver reports the
 *       {@code vector} extension type before {@code registerTypes()} is called);</li>
 *   <li>writes use the pgvector text literal {@code [0.1,0.2,...]} via
 *       {@code setObject(..., Types.OTHER)}, which PostgreSQL infers from the
 *       target column; the literal is built directly so no per-connection
 *       {@code PGvector.registerTypes()} wiring is required;</li>
 *   <li>reads accept {@link PGvector}, {@code float[]}, {@link PGobject} and
 *       plain string representations and normalise them to {@code float[]}.</li>
 * </ul>
 *
 * <p>The literal parser accepts the format PostgreSQL returns for a vector
 * column ({@code [0.1,0.2,0.3]}).
 */
public class VectorType implements UserType<float[]> {

    @Override
    public int getSqlType() {
        return Types.OTHER;
    }

    @Override
    public Class<float[]> returnedClass() {
        return float[].class;
    }

    @Override
    public boolean equals(float[] x, float[] y) {
        return Arrays.equals(x, y);
    }

    @Override
    public int hashCode(float[] x) {
        return Arrays.hashCode(x);
    }

    @Override
    public float[] nullSafeGet(ResultSet rs, int position,
                               SharedSessionContractImplementor session, Object owner)
            throws SQLException {
        Object value = rs.getObject(position);
        if (value == null) {
            return null;
        }
        if (value instanceof PGvector pv) {
            return pv.toArray();
        }
        if (value instanceof float[] fa) {
            return fa;
        }
        // PGJDBC returns the text literal (e.g. "[0.1,0.2,0.3]") as a String /
        // PGobject for unregistered extension types — PGobject.toString() is the
        // raw value, so String.valueOf() covers both.
        return parseVectorLiteral(String.valueOf(value));
    }

    @Override
    public void nullSafeSet(PreparedStatement ps, float[] value, int index,
                            SharedSessionContractImplementor session) throws SQLException {
        if (value == null) {
            ps.setNull(index, Types.OTHER);
        } else {
            ps.setObject(index, toVectorLiteral(value), Types.OTHER);
        }
    }

    @Override
    public float[] deepCopy(float[] value) {
        return value == null ? null : value.clone();
    }

    @Override
    public boolean isMutable() {
        return true;
    }

    @Override
    public Serializable disassemble(float[] value) {
        return deepCopy(value);
    }

    @Override
    public float[] assemble(Serializable cached, Object owner) {
        return (float[]) cached;
    }

    @Override
    public float[] replace(float[] detached, float[] managed, Object owner) {
        return deepCopy(detached);
    }

    /** Formats a vector as the pgvector text literal, e.g. {@code [0.1,0.2]}. */
    private static String toVectorLiteral(float[] vec) {
        StringBuilder sb = new StringBuilder(vec.length * 8 + 2);
        sb.append('[');
        for (int i = 0; i < vec.length; i++) {
            if (i > 0) {
                sb.append(',');
            }
            sb.append(vec[i]);
        }
        sb.append(']');
        return sb.toString();
    }

    /** Parses a pgvector literal ({@code [0.1,0.2,...]}) into a {@code float[]}. */
    private static float[] parseVectorLiteral(String literal) {
        String s = literal == null ? "" : literal.trim();
        if (s.startsWith("[") && s.endsWith("]") && s.length() >= 2) {
            s = s.substring(1, s.length() - 1);
        }
        if (s.isBlank()) {
            return new float[0];
        }
        String[] parts = s.split(",");
        float[] vec = new float[parts.length];
        for (int i = 0; i < parts.length; i++) {
            vec[i] = Float.parseFloat(parts[i].trim());
        }
        return vec;
    }
}
