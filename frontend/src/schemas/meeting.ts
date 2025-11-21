import {z} from 'zod';

const isBrowserFile = (value: unknown): value is File =>
    typeof File !== 'undefined' && value instanceof File;

export const MeetingSchema = z.object({
    title: z.string().min(3, 'Title must be at least 3 characters'),
    startedAt: z.string().min(1, 'Start time is required'),
    file: z
        .any()
        .refine((value): value is File => isBrowserFile(value), {
            message: 'Audio file is required',
        }),
});

export type MeetingFormValues = z.infer<typeof MeetingSchema>;

export const MeetingUpdateSchema = z.object({
    title: z.string().min(3, 'Title must be at least 3 characters'),
    startedAt: z.string().min(1, 'Start time is required'),
});

export type MeetingUpdateValues = z.infer<typeof MeetingUpdateSchema>;
