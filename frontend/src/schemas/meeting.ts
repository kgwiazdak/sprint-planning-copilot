import { z } from 'zod';

export const MeetingSchema = z
  .object({
    title: z.string().min(3, 'Title must be at least 3 characters'),
    startedAt: z.string().min(1, 'Start time is required'),
    sourceUrl: z.string().url('Must be a valid URL').optional(),
    sourceText: z.string().optional(),
  })
  .superRefine((data, ctx) => {
    if (!data.sourceUrl && !data.sourceText) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Provide a source URL or transcript text',
        path: ['sourceUrl'],
      });
    }
  });

export type MeetingFormValues = z.infer<typeof MeetingSchema>;

export const MeetingUpdateSchema = z.object({
  title: z.string().min(3, 'Title must be at least 3 characters'),
  startedAt: z.string().min(1, 'Start time is required'),
});

export type MeetingUpdateValues = z.infer<typeof MeetingUpdateSchema>;
