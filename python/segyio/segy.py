import warnings
try:
    from future_builtins import zip
    range = xrange
except (NameError, ImportError): pass

import numpy as np

from .gather import Gather
from .line import Line
from .trace import Trace, Header
from .field import Field

from segyio.tracesortingformat import TraceSortingFormat



class SegyFile(object):
    """
    This class is not meant to be instantiated directly, but rather obtained
    from ``segyio.open`` or ``segyio.create``.
    """

    _unstructured_errmsg = "File opened in unstructured mode."

    def __init__(self, filename, mode, iline=189, xline=193, tracecount=0, binary=None):
        self._filename = filename
        self._mode = mode
        self._il = iline
        self._xl = xline

        # property value holders
        self._ilines = None
        self._xlines = None
        self._offsets = None
        self._samples = None
        self._sorting = None

        # private values
        self._iline_length = None
        self._iline_stride = None
        self._xline_length = None
        self._xline_stride = None

        from . import _segyio

        self.xfd = _segyio.segyiofd(str(filename), mode,
                                    tracecount=tracecount,
                                    binary=binary,
                                   )
        metrics = self.xfd.metrics()
        self._fmt = metrics['format']
        self._tracecount = metrics['tracecount']
        self._ext_headers = metrics['ext_headers']

        try:
            self._dtype = np.dtype({
                1: np.float32,
                2: np.int32,
                3: np.int16,
                5: np.float32,
                8: np.int8,
            }[self._fmt])
        except KeyError:
            problem = 'Unknown trace value format {}'.format(self._fmt)
            solution = 'falling back to ibm float'
            warnings.warn(', '.join((problem, solution)))
            self._fmt = 1
            self._dtype = np.dtype(np.float32)

        self._trace = Trace(self.xfd,
                            self.dtype,
                            self.tracecount,
                            metrics['samplecount'],
                            self.readonly,
                           )
        self._header = Header(self)
        self._iline = None
        self._xline = None
        self._gather = None
        self.depth = None

        super(SegyFile, self).__init__()

    def __str__(self):
        f = "SegyFile {}:".format(self._filename)

        if self.unstructured:
            il =  "  inlines: None"
            xl =  "  crosslines: None"
            of =  "  offsets: None"
        else:
            il =  "  inlines: {} [{}, {}]".format(len(self.ilines), self.ilines[0], self.ilines[-1])
            xl =  "  crosslines: {} [{}, {}]".format(len(self.xlines), self.xlines[0], self.xlines[-1])
            of =  "  offsets: {} [{}, {}]".format(len(self.offsets), self.offsets[0], self.offsets[-1])

        tr =  "  traces: {}".format(self.tracecount)
        sm =  "  samples: {}".format(self.samples)
        fmt = "  float representation: {}".format(self.format)

        props = [f, il, xl, tr, sm]

        if self.offsets is not None and len(self.offsets) > 1:
            props.append(of)

        props.append(fmt)
        return '\n'.join(props)


    def __repr__(self):
        return "SegyFile('{}', '{}', iline = {}, xline = {})".format(
                        self._filename, self._mode, self._il, self._xl)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def flush(self):
        """Flush the file

        Write the library buffers to disk, like C's ``fflush``. This method is
        mostly useful for testing.

        It is not necessary to call this method unless you want to observe your
        changes on-disk while the file is still open. The file will
        automatically be flushed for you if you use the `with` statement when
        your routine is completed.

        Notes
        -----

        .. versionadded:: 1.1

        .. warning::
            This is not guaranteed to actually write changes to disk, it only
            flushes the library buffers. Your kernel is free to defer writing
            changes to disk until a later time.

        Examples
        --------

        Flush:

        >>> with segyio.open(path) as f:
        ...     # write something to f
        ...     f.flush()

        """
        self.xfd.flush()

    def close(self):
        """Close the file

        This method is mostly useful for testing.

        It is not necessary to call this method if you're using the `with`
        statement, which will close the file for you. Calling methods on a
        previously-closed file will raise `IOError`.

        Notes
        -----

        .. versionadded:: 1.1


        """
        self.xfd.close()

    def mmap(self):
        """Memory map the file

        Memory map the file. This is an advanced feature for speed and
        optimization; however, it is no silver bullet. If your file is smaller
        than the memory available on your system this will likely result in
        faster reads and writes, especially for line modes. However, if the
        file is very large, or memory is very pressured, this optimization
        might cause overall system slowdowns. However, if you're opening the
        same file from many different instances of segyio then memory mapping
        may significantly reduce the memory pressure.

        If this call returns true, the file is memory mapped. If memory mapping
        was build-time disabled or is not available for your platform this call
        always return false. If the memory mapping is unsuccessful you can keep
        using segyio - reading and writing falls back on non-memory mapped
        features.

        Returns
        -------

        success : bool
            Returns True if the file was successfully memory mapped, False if
            not

        Notes
        -----

        .. versionadded:: 1.1


        Examples
        --------

        Memory map:

        >>> mapped = f.mmap()
        >>> if mapped: print( "File is memory mapped!" )
        File is memory mapped!
        >>> pass # keep using segyio as per usual
        >>> print( f.trace[10][7] )
        1.02548

        """
        return self.xfd.mmap()

    @property
    def dtype(self):
        """

        The data type object of the traces. This is the format most accurate
        and efficient to exchange with the underlying file, and the data type
        you will find the data traces.

        Returns
        -------

        dtype : numpy.dtype

        Notes
        -----

        .. versionadded:: 1.6

        """
        return self._dtype

    @property
    def sorting(self):
        """

        Inline or crossline sorting, or Falsey (None or 0) if unstructured.
        Returns
        -------

        sorting : int

        """
        return self._sorting

    @property
    def tracecount(self):
        """Number of traces in this file

        Equivalent to ``len(f.trace)``

        Returns
        -------

        count : int
            Number of traces in this file

        """
        return self._tracecount

    @property
    def samples(self):
        """
        Return the array of samples with appropriate intervals.

        Returns
        -------

        samples : numpy.ndarray of int

        Notes
        -----

        It holds that ``len(f.samples) == len(f.trace[0])``

        """

        return self._samples

    @property
    def offsets(self):
        """

        Return the array of offset names. For post-stack data, this array has a
        length of 1

        Returns
        -------

        offsets : numpy.ndarray of int

        """
        return self._offsets

    @property
    def ext_headers(self):
        """Extra text headers

        The number of extra text headers, given by the ``ExtendedHeaders``
        field in the binary header.

        Returns
        -------

        headers : int
            Number of extra text headers

        """

        return self._ext_headers

    @property
    def unstructured(self):
        """
        If the file is unstructured, sophisticated addressing modes that
        require the file to represent a proper cube won't work, and only raw
        data reading and writing is supported.

        Returns
        -------

        unstructured : bool
            ``True`` if this file is unstructured, ``False`` if not

        """
        return self.ilines is None

    @property
    def header(self):
        """
        Interact with segy in header mode

        Returns
        -------
        header : Header

        Notes
        -----
        .. versionadded:: 1.1
        """
        return self._header

    @header.setter
    def header(self, val):
        """headers macro assignment

        A convenient way for operating on all headers of a file is to use the
        default full-file range.  It will write headers 0, 1, ..., n, but uses
        the iteration specified by the right-hand side (i.e. can skip headers
        etc).

        If the right-hand-side headers are exhausted before all the destination
        file headers the writing will stop, i.e. not all all headers in the
        destination file will be written to.

        Examples
        --------
        Copy headers from file g to file f:

        >>> f.header = g.header

        Set offset field:

        >>> f.header = { TraceField.offset: 5 }

        Copy every 12th header from the file g to f's 0, 1, 2...:

        >>> f.header = g.header[::12]
        >>> f.header[0] == g.header[0]
        True
        >>> f.header[1] == g.header[12]
        True
        >>> f.header[2] == g.header[2]
        False
        >>> f.header[2] == g.header[24]
        True
        """
        self.header[:] = val

    def attributes(self, field):
        """File-wide attribute (header word) reading

        Lazily gather a single header word for every trace in the file. The
        array can be sliced, supports index lookup, and numpy-style
        list-of-indices.

        Parameters
        ----------

        field : int or segyio.TraceField
            field

        Returns
        -------

        attrs : list of int
            A sliceable list of header words

        Notes
        -----

        .. versionadded:: 1.1

        Examples
        --------

        Read all unique sweep frequency end::

        >>> end = segyio.TraceField.SweepFrequencyEnd
        >>> sfe = np.unique(f.attributes( end )[:])

        Discover the first traces of each unique sweep frequency end:

        >>> end = segyio.TraceField.SweepFrequencyEnd
        >>> attrs = f.attributes(end)
        >>> sfe, tracenos = np.unique(attrs[:], return_index = True)

        Scatter plot group x/y-coordinates with SFEs (using matplotlib):

        >>> end = segyio.TraceField.SweepFrequencyEnd
        >>> attrs = f.attributes(end)
        >>> _, tracenos = np.unique(attrs[:], return_index = True)
        >>> gx = f.attributes(segyio.TraceField.GroupX)[tracenos]
        >>> gy = f.attributes(segyio.TraceField.GroupY)[tracenos]
        >>> scatter(gx, gy)

        """
        class attr:
            def __getitem__(inner, rng):
                try: iter(rng)
                except TypeError: pass
                else: return inner._getitem_list(rng)

                if not isinstance(rng, slice):
                    rng = slice(rng, rng + 1, 1)

                traces = self.tracecount
                start, stop, step = rng.indices(traces)
                attrs = np.empty(len(range(*rng.indices(traces))), dtype = np.intc)
                return self.xfd.field_forall(attrs, start, stop, step, field)

            def _getitem_list(inner, xs):
                if not isinstance(xs, np.ndarray):
                    xs = np.asarray(xs, dtype = np.intc)

                xs = xs.astype(dtype = np.intc, order = 'C', copy = False)
                attrs = np.empty(len(xs), dtype = np.intc)
                return self.xfd.field_foreach(attrs, xs, field)

        return attr()


    @property
    def trace(self):
        """
        Interact with segy in trace mode.

        Returns
        -------
        trace : Trace

        Notes
        -----
        .. versionadded:: 1.1

        """

        return self._trace

    @trace.setter
    def trace(self, val):
        """traces macro assignment

        Convenient way for setting traces from 0, 1, ... n, based on the
        iterable set of traces on the right-hand-side.

        If the right-hand-side traces are exhausted before all the destination
        file traces the writing will stop, i.e. not all all traces in the
        destination file will be written.

        Notes
        -----
        .. versionadded:: 1.1

        Examples
        --------
        Copy traces from file f to file g:

        >>> f.trace = g.trace

        Copy first half of the traces from g to f:

        >>> f.trace = g.trace[:len(g.trace)/2]

        Fill the file with one trace (filled with zeros):

        >>> tr = np.zeros(f.samples)
        >>> f.trace = itertools.repeat(tr)

        For advanced users: sometimes you want to load the entire segy file
        to memory and apply your own structural manipulations or operations
        on it. Some segy files are very large and may not fit, in which
        case this feature will break down. This is an optimisation feature;
        using it should generally be driven by measurements.

        Read the first 10 traces:

        >>> f.trace.raw[0:10]

        Read *all* traces to memory:

        >>> f.trace.raw[:]

        Read every other trace to memory:

        >>> f.trace.raw[::2]
        """
        self.trace[:] = val

    @property
    def ilines(self):
        """Inline labels

        The inline labels in this file, if structured, else None

        Returns
        -------

        inlines : array_like of int or None

        """
        return self._ilines

    @property
    def iline(self):
        """
        Interact with segy in inline mode

        Returns
        -------
        iline : Line or None

        Raises
        ------
        ValueError
            If the file is unstructured

        Notes
        -----
        .. versionadded:: 1.1
        """

        if self.unstructured:
            raise ValueError(self._unstructured_errmsg)

        if self._iline is not None:
            return self._iline

        self._iline = Line(self,
                           self.ilines,
                           self._iline_length,
                           self._iline_stride,
                           self.offsets,
                           'inline',
                          )
        return self._iline

    @iline.setter
    def iline(self, value):
        """inlines macro assignment

        Convenient way for setting inlines, from left-to-right as the inline
        numbers are specified in the file.ilines property, from an iterable
        set on the right-hand-side.

        If the right-hand-side inlines are exhausted before all the destination
        file inlines the writing will stop, i.e. not all all inlines in the
        destination file will be written.

        Notes
        -----
        .. versionadded:: 1.1

        Examples
        --------
        Copy inlines from file f to file g:

        >>> f.iline = g.iline
        """
        self.iline[:] = value

    @property
    def xlines(self):
        """Crossline labels

        The crosslane labels in this file, if structured, else None

        Returns
        -------

        crosslines : array_like of int or None

        """
        return self._xlines

    @property
    def xline(self):
        """
        Interact with segy in crossline mode

        Returns
        -------
        xline : Line or None

        Raises
        ------
        ValueError
            If the file is unstructured

        Notes
        -----
        .. versionadded:: 1.1
        """
        if self.unstructured:
            raise ValueError(self._unstructured_errmsg)

        if self._xline is not None:
            return self._xline

        self._xline = Line(self,
                           self.xlines,
                           self._xline_length,
                           self._xline_stride,
                           self.offsets,
                           'crossline',
                          )
        return self._xline

    @xline.setter
    def xline(self, value):
        """crosslines macro assignment

        Convenient way for setting crosslines, from left-to-right as the inline
        numbers are specified in the file.ilines property, from an iterable set
        on the right-hand-side.

        If the right-hand-side inlines are exhausted before all the destination
        file inlines the writing will stop, i.e. not all all inlines in the
        destination file will be written.

        Notes
        -----
        .. versionadded:: 1.1

        Examples
        --------
        Copy crosslines from file f to file g:

        >>> f.xline = g.xline
        """
        self.xline[:] = value

    @property
    def fast(self):
        """Access the 'fast' dimension

        This mode yields iline or xline mode, depending on which one is laid
        out `faster`, i.e. the line with linear disk layout. Use this mode if
        the inline/crossline distinction isn't as interesting as traversing in
        a fast manner (typically when you want to apply a function to the whole
        file, line-by-line).

        Returns
        -------
        fast : Line
            line addressing mode

        Notes
        -----
        .. versionadded:: 1.1
        """
        if self.sorting == TraceSortingFormat.INLINE_SORTING:
            return self.iline
        elif self.sorting == TraceSortingFormat.CROSSLINE_SORTING:
            return self.xline
        else:
            raise RuntimeError("Unknown sorting.")

    @property
    def slow(self):
        """Access the 'slow' dimension

        This mode yields iline or xline mode, depending on which one is laid
        out `slower`, i.e. the line with strided disk layout. Use this mode if
        the inline/crossline distinction isn't as interesting as traversing in
        the slower direction.

        Returns
        -------
        slow : Line
            line addressing mode

        Notes
        -----
        .. versionadded:: 1.1
        """
        if self.sorting == TraceSortingFormat.INLINE_SORTING:
            return self.xline
        elif self.sorting == TraceSortingFormat.CROSSLINE_SORTING:
            return self.iline
        else:
            raise RuntimeError("Unknown sorting.")

    @property
    def depth_slice(self):
        """
        Interact with segy in depth slice mode

        Returns
        -------
        depth : Depth
        """

        if self.unstructured:
            raise ValueError(self._unstructured_errmsg)

        if self.depth is not None:
            return self.depth

        from .depth import Depth
        self.depth = Depth(self)
        return self.depth

    @depth_slice.setter
    def depth_slice(self, value):
        """depth macro assignment

        Convenient way for setting depth slices, from left-to-right as the depth slices
        numbers are specified in the file.depth_slice property, from an iterable
        set on the right-hand-side.

        If the right-hand-side depth slices are exhausted before all the destination
        file depth slices the writing will stop, i.e. not all all depth slices in the
        destination file will be written.

        Examples
        --------
        Copy depth slices from file f to file g:

        >>> f.depth_slice = g.depth_slice

        Copy first half of the depth slices from g to f:

        >>> f.depth_slice = g.depth_slice[:g.samples/2]]
        """
        self.depth_slice[:] = value

    @property
    def gather(self):
        """
        Interact with segy in gather mode

        Returns
        -------
        gather : Gather
        """
        if self.unstructured:
            raise ValueError(self._unstructured_errmsg)

        if self._gather is not None:
            return self._gather

        self._gather = Gather(self.trace, self.iline, self.xline, self.offsets)
        return self._gather

    @property
    def text(self):
        """Interact with segy in text mode

        This mode gives access to reading and writing functionality for textual
        headers.

        The primary data type is the python string. Reading textual headers is
        done with ``[]``, and writing is done via assignment. No additional
        structure is built around the textual header, so everything is treated
        as one long string without line breaks.

        Returns
        -------

        text
            text headers

        See also
        --------

        segyio.tools.wrap : line-wrap a text header

        Notes
        -----

        .. versionadded:: 1.1


        Examples
        --------

        Print the textual header:

        >>> print(f.text[0])

        Print the first extended textual header:

        >>> print(f.text[1])

        Write a new textual header:

        >>> f.text[0] = make_new_header()

        Copy a tectual header:

        >>> f.text[1] = g.text[0]

        Print a textual header line-by-line:

        >>> # using zip, from the zip documentation
        >>> text = str(f.text[0])
        >>> lines = map(''.join, zip( *[iter(text)] * 80))
        >>> for line in lines:
        ...     print(line)
        ...


        """
        return TextHeader(self)

    @property
    def bin(self):
        """
        Interact with segy in binary mode

        This mode gives access to reading and writing functionality for the
        binary header. Please note that using numeric binary offsets uses the
        offset numbers from the specification, i.e. the first field of the
        binary header starts at 3201, not 1. If you're using the enumerations
        this is handled for you.

        Returns
        -------
        binary : Field

        Notes
        -----
        .. versionadded:: 1.1
        """

        return Field.binary(self)

    @bin.setter
    def bin(self, value):
        """Update binary header

        Update a value or replace the binary header

        Parameters
        ----------

        value : dict_like
            dict_like, keys of int or segyio.BinField or segyio.su

        """
        self.bin.update(value)

    @property
    def format(self):
        d = {
            1: "4-byte IBM float",
            2: "4-byte signed integer",
            3: "2-byte signed integer",
            4: "4-byte fixed point with gain",
            5: "4-byte IEEE float",
            8: "1-byte signed char"
        }

        class fmt:
            def __int__(inner):
                return self._fmt

            def __str__(inner):
                if not self._fmt in d:
                    return "Unknown format"

                return d[self._fmt]

        return fmt()

    @property
    def readonly(self):
        """File is read-only

        Returns
        -------
        readonly : bool
            True if this file is read-only

        Notes
        -----
        .. versionadded:: 1.6
        """

        return '+' not in self._mode

class spec:
    def __init__(self):
        self.iline = 189
        self.ilines = None
        self.xline = 193
        self.xlines = None
        self.offsets = [1]
        self.samples = None
        self.ext_headers = 0
        self.format = None
        self.sorting = None

class TextHeader(object):

    def __init__(self, outer):
        self.outer = outer

    def __getitem__(self, index):
        if not 0 <= index <= self.outer.ext_headers:
            raise IndexError("Textual header {} not in file".format(index))

        return self.outer.xfd.gettext(index)

    def __setitem__(self, index, val):
        if isinstance(val, TextHeader):
            self[index] = val[0]
            return

        if not 0 <= index <= self.outer.ext_headers:
            raise IndexError("Textual header {} not in file".format(index))

        self.outer.xfd.puttext(index, val)

    def __repr__(self):
        return "Text(external_headers = {})".format(self.outer.ext_headers)

    def __str__(self):
        msg = 'str(text) is deprecated, use explicit format instead'
        warnings.warn(DeprecationWarning, msg)
        return '\n'.join(map(''.join, zip(*[iter(str(self[0]))] * 80)))
